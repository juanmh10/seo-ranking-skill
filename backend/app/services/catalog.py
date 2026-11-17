import hashlib

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.execution import EvalDefinition, ModelConfig, ModelRegistry, Prompt, Run, RunConfig
from app.services.evaluation import (
    LLM_JUDGE_METRICS,
    LLM_JUDGE_PROMPT_CONTENT,
    LLM_JUDGE_PROMPT_NAME,
    LLM_JUDGE_PROMPT_VERSION,
    LLM_JUDGE_VERSION,
)

DEFAULT_PROMPT_NAME = "Assistente neutro"
DEFAULT_PROMPT_CONTENT = (
    "You are a general-purpose AI assistant. Answer the user's request using the "
    "provided retrieved information when relevant."
)


async def sync_catalog(session: AsyncSession, settings: Settings) -> None:
    """Sync local configuration only; never contacts Vertex AI."""
    await session.execute(update(ModelRegistry).values(enabled=False))
    for configured in settings.model_registry:
        model = await session.get(ModelRegistry, configured.model_id)
        if model is None:
            model = ModelRegistry(model_id=configured.model_id, metadata_json={})
            session.add(model)
        for key, value in configured.model_dump().items():
            setattr(model, key, value)

        if model.last_verified_at is None:
            verified_at = await session.scalar(
                select(func.max(Run.completed_at))
                .join(RunConfig, RunConfig.id == Run.run_config_id)
                .join(ModelConfig, ModelConfig.id == RunConfig.model_config_id)
                .where(
                    ModelConfig.model_id == configured.model_id,
                    Run.status == "completed",
                    Run.response_text.is_not(None),
                )
            )
            if verified_at is not None:
                model.last_verified_at = verified_at

    existing = await session.scalar(
        select(Prompt.id).where(Prompt.name == DEFAULT_PROMPT_NAME, Prompt.type == "system")
    )
    if existing is None:
        session.add(
            Prompt(
                name=DEFAULT_PROMPT_NAME,
                type="system",
                content=DEFAULT_PROMPT_CONTENT,
                version=1,
                sha256=hashlib.sha256(DEFAULT_PROMPT_CONTENT.encode()).hexdigest(),
            )
        )
    evaluation_prompt = await session.scalar(
        select(Prompt).where(
            Prompt.name == LLM_JUDGE_PROMPT_NAME,
            Prompt.type == "evaluation",
            Prompt.version == LLM_JUDGE_PROMPT_VERSION,
        )
    )
    if evaluation_prompt is None:
        evaluation_prompt = Prompt(
            name=LLM_JUDGE_PROMPT_NAME,
            type="evaluation",
            content=LLM_JUDGE_PROMPT_CONTENT,
            version=LLM_JUDGE_PROMPT_VERSION,
            sha256=hashlib.sha256(LLM_JUDGE_PROMPT_CONTENT.encode()).hexdigest(),
        )
        session.add(evaluation_prompt)
        await session.flush()

    defaults = [
        (
            "target_selection_rate",
            "Target selection rate",
            "Scores whether the first entity following an explicit recommendation cue "
            "is the expected target.",
            "deterministic",
            None,
        ),
        (
            "target_rank",
            "Target mention rank",
            "Ranks the expected target by the first explicit mention of each configured entity.",
            "deterministic",
            None,
        ),
    ]
    defaults.extend(
        (
            metric_name,
            name,
            f"LLM judge scorer for {metric_name.replace('_', ' ')}.",
            "llm_judge",
            evaluation_prompt.id,
        )
        for metric_name, name in LLM_JUDGE_METRICS
    )
    for metric_name, name, description, evaluator_type, prompt_id in defaults:
        definition_version = 2
        definition_exists = await session.scalar(
            select(EvalDefinition.id).where(
                EvalDefinition.metric_name == metric_name,
                EvalDefinition.version == definition_version,
            )
        )
        if definition_exists is None:
            session.add(
                EvalDefinition(
                    name=name,
                    version=definition_version,
                    evaluator_type=evaluator_type,
                    metric_name=metric_name,
                    description=description,
                    config_json=(
                        {
                            "casefold": True,
                            "word_boundary": True,
                            "evaluator_version": "deterministic-1.1.0",
                        }
                        if evaluator_type == "deterministic"
                        else {
                            "evaluator_version": LLM_JUDGE_VERSION,
                            "response_schema": "LLMJudgeResponse",
                            "temperature": 0,
                        }
                    ),
                    prompt_id=prompt_id,
                )
            )
    await session.commit()


class PromptService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[Prompt]:
        result = await self.session.scalars(
            select(Prompt)
            .where(Prompt.type == "system")
            .order_by(Prompt.name, Prompt.version.desc())
        )
        return list(result.all())

    async def create(self, name: str, content: str) -> Prompt:
        name = name.strip()
        content = content.strip()
        if not name or not content:
            raise ValueError("Prompt name and content cannot be empty")
        version = (
            await self.session.scalar(
                select(func.max(Prompt.version)).where(Prompt.name == name, Prompt.type == "system")
            )
            or 0
        ) + 1
        prompt = Prompt(
            name=name,
            type="system",
            content=content,
            version=version,
            sha256=hashlib.sha256(content.encode()).hexdigest(),
        )
        self.session.add(prompt)
        await self.session.commit()
        await self.session.refresh(prompt)
        return prompt
