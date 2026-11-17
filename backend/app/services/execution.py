from __future__ import annotations

import asyncio
import hashlib
import random
import secrets
import time
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.database import Database
from app.domain.model_runner import ModelRequest, ModelRunner
from app.models.execution import (
    EvalDefinition,
    Event,
    ModelConfig,
    ModelRegistry,
    Prompt,
    Run,
    RunConfig,
    RunDocument,
)
from app.models.experiment import Dataset, DatasetStatus, Experiment
from app.models.source_document import SourceDocument, SourceOrigin, SourceRepresentation
from app.schemas.execution import RunCreate
from app.services.evaluation import EvaluationService
from app.services.source_documents import SourceDocumentService, SourceProvenance
from app.services.source_normalizer import normalize_source


class RunPreflightError(ValueError):
    pass


class RunConflictError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def estimate_tokens(value: str) -> int:
    # Conservative rough preflight, not a substitute for provider token counting.
    return max(1, (len(value.encode("utf-8")) + 1) // 2)


def source_text(document: SourceDocument, mode: str) -> str:
    if mode == "RAW":
        return document.raw_content
    if mode == "NORMALIZED":
        return document.normalized_content
    return (
        f"[RAW]\n{document.raw_content}\n[/RAW]\n"
        f"[NORMALIZED]\n{document.normalized_content}\n[/NORMALIZED]"
    )


def _identity_value(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def _aliases_identity(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted({_identity_value(value) for value in values if _identity_value(value)}))


def ordered_documents(
    documents: list[SourceDocument], strategy: str, seed: int | None, number: int
) -> list[SourceDocument]:
    ordered = list(documents)
    if strategy == "fixed":
        return ordered
    assert seed is not None
    if strategy == "counterbalanced":
        random.Random(seed).shuffle(ordered)
        offset = (number - 1) % len(ordered)
        return ordered[offset:] + ordered[:offset]
    random.Random(seed + number - 1).shuffle(ordered)
    return ordered


class ExecutionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def create(
        self, experiment_id: str, payload: RunCreate, idempotency_key: str
    ) -> tuple[RunConfig, bool]:
        request_sha256 = hashlib.sha256(
            payload.model_dump_json(exclude_none=False).encode("utf-8")
        ).hexdigest()
        previous = await self.session.scalar(
            select(RunConfig).where(
                RunConfig.experiment_id == experiment_id,
                RunConfig.idempotency_key == idempotency_key,
            )
        )
        if previous is not None:
            if previous.request_sha256 != request_sha256:
                raise RunConflictError("Idempotency-Key was already used with a different payload")
            return previous, False

        experiment = await self.session.get(Experiment, experiment_id)
        if experiment is None:
            raise LookupError("Experiment not found")
        if experiment.status == "archived":
            raise RunConflictError("Archived experiments cannot be executed")
        if not payload.user_prompt.strip():
            raise RunPreflightError("A non-empty question is required")
        if not self.settings.gcp_project:
            raise RunPreflightError("APP_GCP_PROJECT must be configured before a run")
        model = await self.session.get(ModelRegistry, payload.model_id)
        if model is None or not model.enabled:
            raise RunPreflightError("Selected model is not enabled in APP_MODEL_REGISTRY")
        if model.endpoint_type not in {"vertex_gemini", "vertex_anthropic", "xai_responses"}:
            raise RunPreflightError(
                "Selected model endpoint is not supported by the current runner"
            )
        if model.endpoint_type == "xai_responses" and not (
            self.settings.xai_api_key
            and self.settings.xai_api_key.get_secret_value().strip()
        ):
            raise RunPreflightError("APP_XAI_API_KEY must be configured to use Grok models")
        prompt = await self.session.get(Prompt, payload.system_prompt_id)
        if prompt is None or prompt.type != "system":
            raise RunPreflightError("Select a versioned system prompt")
        if payload.temperature is not None and not model.supports_temperature:
            raise RunPreflightError("Selected model does not support temperature")
        if payload.top_p is not None and not model.supports_top_p:
            raise RunPreflightError("Selected model does not support top_p")
        if payload.seed is not None and not model.supports_seed:
            raise RunPreflightError("Selected model does not support seed")

        dataset = await self.session.scalar(
            select(Dataset)
            .where(Dataset.experiment_id == experiment_id)
            .order_by(Dataset.version.desc())
            .limit(1)
        )
        if dataset is None:
            raise RunPreflightError("Experiment has no dataset")
        documents = list(
            (
                await self.session.scalars(
                    select(SourceDocument)
                    .where(
                        SourceDocument.dataset_id == dataset.id,
                        SourceDocument.position.is_not(None),
                    )
                    .options(selectinload(SourceDocument.label))
                    .order_by(SourceDocument.position)
                )
            ).all()
        )
        if len(documents) != 5:
            raise RunPreflightError("Exactly five active sources are required")
        active_targets = [
            document for document in documents if document.label and document.label.expected_target
        ]
        if len(active_targets) != 1:
            raise RunPreflightError("Exactly one active source must be marked expected_target")
        if any(document.label is None for document in documents):
            raise RunPreflightError("All active sources need labels")

        active_target = active_targets[0]
        target_scenarios = [active_target]
        if payload.counterfactual_document_ids:
            candidate_rows = list(
                (
                    await self.session.scalars(
                        select(SourceDocument)
                        .where(
                            SourceDocument.dataset_id == dataset.id,
                            SourceDocument.id.in_(payload.counterfactual_document_ids),
                        )
                        .options(selectinload(SourceDocument.label))
                    )
                ).all()
            )
            candidates_by_id = {document.id: document for document in candidate_rows}
            if len(candidates_by_id) != len(payload.counterfactual_document_ids):
                raise RunPreflightError(
                    "Every counterfactual source must belong to the current dataset"
                )
            candidates = [
                candidates_by_id[document_id]
                for document_id in payload.counterfactual_document_ids
            ]
            target_scenarios.extend(candidates)
            group_key = (active_target.counterfactual_group_key or "").strip()
            if not group_key:
                raise RunPreflightError(
                    "Set a counterfactual group key on the active target and its variants"
                )
            base_identity = (
                _identity_value(active_target.entity_key),
                _identity_value(active_target.entity_name),
                _aliases_identity(active_target.aliases_json),
            )
            if not base_identity[0] or not base_identity[1]:
                raise RunPreflightError(
                    "Counterfactual variants require the same non-empty entity key and entity name"
                )
            condition_labels: set[tuple[str, str]] = set()
            for candidate in candidates:
                if candidate.position is not None:
                    raise RunPreflightError(
                        "Counterfactual variants must remain outside the five active source slots"
                    )
                if candidate.label is None or not candidate.label.expected_target:
                    raise RunPreflightError(
                        "Every counterfactual variant must be labeled expected_target"
                    )
                if (candidate.counterfactual_group_key or "").strip() != group_key:
                    raise RunPreflightError(
                        "All target variants must use the same counterfactual group key"
                    )
                candidate_identity = (
                    _identity_value(candidate.entity_key),
                    _identity_value(candidate.entity_name),
                    _aliases_identity(candidate.aliases_json),
                )
                if candidate_identity != base_identity:
                    raise RunPreflightError(
                        "Counterfactual variants must preserve the target entity key, "
                        "name, and aliases"
                    )
                if (
                    candidate.mime_type != active_target.mime_type
                    or candidate.source_representation != active_target.source_representation
                ):
                    raise RunPreflightError(
                        "Counterfactual variants must preserve the target source format"
                    )
            for variant in target_scenarios:
                assert variant.label is not None
                condition = (variant.label.severity, variant.label.technique)
                if condition in condition_labels:
                    raise RunPreflightError(
                        "Each counterfactual variant must have a distinct "
                        "severity/technique condition"
                    )
                condition_labels.add(condition)
            if sum(
                variant.label is not None
                and variant.label.severity == "neutral"
                and variant.label.technique == "none"
                for variant in target_scenarios
            ) != 1:
                raise RunPreflightError(
                    "A counterfactual comparison requires exactly one neutral/none control"
                )
            if not any(
                variant.label is not None
                and (variant.label.severity != "neutral" or variant.label.technique != "none")
                for variant in target_scenarios
            ):
                raise RunPreflightError(
                    "Add at least one manipulated target variant to calculate Manipulation Lift"
                )

        scenario_sources = [
            (
                target,
                [target if document.id == active_target.id else document for document in documents],
            )
            for target in target_scenarios
        ]
        scenario_texts = {
            target.id: [source_text(document, payload.content_mode) for document in sources]
            for target, sources in scenario_sources
        }
        estimated_context_by_scenario = {
            target_id: sum(estimate_tokens(text) for text in texts)
            + estimate_tokens(prompt.content + payload.user_prompt)
            + 512
            for target_id, texts in scenario_texts.items()
        }
        estimated_context = max(estimated_context_by_scenario.values())
        for target_id, context_tokens in estimated_context_by_scenario.items():
            if context_tokens + payload.max_output_tokens > model.max_context:
                raise RunPreflightError(
                    f"Estimated context for target {target_id} ({context_tokens} tokens) "
                    "plus output exceeds model limit"
                )

        evaluation_model_config: ModelConfig | None = None
        if payload.evaluator_model_id:
            evaluator_model = await self.session.get(ModelRegistry, payload.evaluator_model_id)
            if evaluator_model is None or not evaluator_model.enabled:
                raise RunPreflightError(
                    "Selected evaluation model is not enabled in APP_MODEL_REGISTRY"
                )
            if evaluator_model.endpoint_type != "vertex_gemini":
                raise RunPreflightError(
                    "This evaluation model endpoint is not supported by the current runner"
                )
            if not evaluator_model.supports_structured_output:
                raise RunPreflightError(
                    "The evaluation model must support structured JSON output"
                )
            evaluator_definition = await self.session.scalar(
                select(EvalDefinition).where(
                    EvalDefinition.metric_name == "injection_compliance",
                    EvalDefinition.evaluator_type == "llm_judge",
                )
                .order_by(EvalDefinition.version.desc())
                .limit(1)
            )
            evaluator_prompt = (
                await self.session.get(Prompt, evaluator_definition.prompt_id)
                if evaluator_definition and evaluator_definition.prompt_id
                else None
            )
            if evaluator_prompt is None:
                raise RunPreflightError("The versioned model evaluation prompt is unavailable")
            estimated_judge_context = max(
                estimate_tokens(
                    evaluator_prompt.content + payload.user_prompt + "\n".join(texts)
                )
                for texts in scenario_texts.values()
            )
            estimated_judge_context += payload.max_output_tokens + 3072
            if estimated_judge_context > evaluator_model.max_context:
                raise RunPreflightError(
                    "The selected evaluation model context limit is too small for this run"
                )
            evaluation_model_config = ModelConfig(
                provider=evaluator_model.provider,
                model_id=evaluator_model.model_id,
                display_name=evaluator_model.display_name,
                location=evaluator_model.location,
                temperature=0 if evaluator_model.supports_temperature else None,
                top_p=None,
                seed=None,
                max_output_tokens=2048,
                thinking_config_json={},
                extra_config_json={
                    "project": self.settings.gcp_project,
                    "max_context": evaluator_model.max_context,
                    "endpoint_type": evaluator_model.endpoint_type,
                    "role": "evaluator",
                },
            )
            self.session.add(evaluation_model_config)
            await self.session.flush()

        effective_seed = payload.random_seed
        if payload.ordering_strategy != "fixed" and effective_seed is None:
            effective_seed = secrets.randbelow(2147483647)
        model_config = ModelConfig(
            provider=model.provider,
            model_id=model.model_id,
            display_name=model.display_name,
            location=model.location,
            temperature=payload.temperature,
            top_p=payload.top_p,
            seed=payload.seed,
            max_output_tokens=payload.max_output_tokens,
            thinking_config_json={},
            extra_config_json={
                "project": self.settings.gcp_project,
                "max_context": model.max_context,
                "endpoint_type": model.endpoint_type,
            },
        )
        self.session.add(model_config)
        await self.session.flush()
        config = RunConfig(
            experiment_id=experiment_id,
            dataset_id=dataset.id,
            model_config_id=model_config.id,
            system_prompt_id=prompt.id,
            evaluation_model_config_id=(
                evaluation_model_config.id if evaluation_model_config else None
            ),
            user_prompt=payload.user_prompt.strip(),
            content_mode=payload.content_mode,
            ordering_strategy=payload.ordering_strategy,
            random_seed=effective_seed,
            repetitions=payload.repetitions,
            status="queued",
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
        )
        self.session.add(config)
        await self.session.flush()
        run_number = 0
        for repetition in range(1, payload.repetitions + 1):
            for _, sources in scenario_sources:
                run_number += 1
                run = Run(run_config_id=config.id, run_number=run_number, status="queued")
                self.session.add(run)
                await self.session.flush()
                ordered_sources = ordered_documents(
                    sources, payload.ordering_strategy, effective_seed, repetition
                )
                for position, document in enumerate(ordered_sources, start=1):
                    assert document.label is not None
                    content = source_text(document, payload.content_mode)
                    self.session.add(
                        RunDocument(
                            run_id=run.id,
                            document_id=document.id,
                            position=position,
                            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                            content_text=content,
                            tokens_estimated=estimate_tokens(content),
                            label_snapshot_json={
                                "severity": document.label.severity,
                                "technique": document.label.technique,
                                "expected_target": document.label.expected_target,
                                "annotation": document.label.annotation,
                            },
                        )
                    )
        self.session.add(
            Event(
                run_config_id=config.id,
                event_type="run_config_queued",
                payload_json={
                    "repetitions": payload.repetitions,
                    "total_runs": run_number,
                    "estimated_context_tokens": estimated_context,
                    "counterfactual_conditions": [
                        {
                            "document_id": target.id,
                            "severity": target.label.severity if target.label else "unknown",
                            "technique": target.label.technique if target.label else "unknown",
                        }
                        for target in target_scenarios
                    ],
                },
            )
        )
        dataset.status = DatasetStatus.FROZEN.value
        await self.session.commit()
        return await self.get_config(config.id), True

    async def get_config(self, config_id: str) -> RunConfig:
        result = await self.session.scalar(
            select(RunConfig)
            .where(RunConfig.id == config_id)
            .options(
                selectinload(RunConfig.runs)
                .selectinload(Run.documents)
                .defer(RunDocument.content_text)
                .defer(RunDocument.label_snapshot_json),
                selectinload(RunConfig.evaluation_model_config),
            )
        )
        if result is None:
            raise LookupError("Run configuration not found")
        return result

    async def get_run(self, run_id: str, *, include_content: bool = False) -> Run:
        options = selectinload(Run.documents)
        if not include_content:
            options = options.defer(RunDocument.content_text).defer(RunDocument.label_snapshot_json)
        result = await self.session.scalar(select(Run).where(Run.id == run_id).options(options))
        if result is None:
            raise LookupError("Run not found")
        return result

    async def list_configs(self, experiment_id: str) -> list[RunConfig]:
        result = await self.session.scalars(
            select(RunConfig)
            .where(RunConfig.experiment_id == experiment_id)
            .options(
                selectinload(RunConfig.runs)
                .selectinload(Run.documents)
                .defer(RunDocument.content_text)
                .defer(RunDocument.label_snapshot_json)
            )
            .order_by(RunConfig.created_at.desc())
            .limit(20)
        )
        return list(result.all())

    async def promote_output(self, run_id: str, parent_document_id: str | None) -> SourceDocument:
        run = await self.get_run(run_id)
        if run.status != "completed" or not run.response_text:
            raise RunPreflightError("Only completed runs with text can become a source")
        if run.output_document_id:
            return await SourceDocumentService(self.session).get(run.output_document_id)
        config = await self.get_config(run.run_config_id)
        current_dataset = await SourceDocumentService(self.session).current_dataset(
            config.experiment_id
        )
        parent = None
        if parent_document_id:
            parent = await self.session.get(SourceDocument, parent_document_id)
            parent_dataset = (
                await self.session.get(Dataset, parent.dataset_id) if parent is not None else None
            )
            if (
                parent is None
                or parent_dataset is None
                or parent_dataset.experiment_id != config.experiment_id
            ):
                raise RunPreflightError("Parent source must belong to the same experiment")
        source = normalize_source(
            filename=f"run-{run.id}.md",
            data=run.response_text.encode("utf-8"),
            representation=SourceRepresentation.MARKDOWN,
        )
        if source.byte_size > self.settings.max_source_bytes:
            raise RunPreflightError("Model output exceeds the source size limit")
        iteration = (
            max(
                (
                    document.iteration
                    for document in (
                        await self.session.scalars(
                            select(SourceDocument).where(
                                SourceDocument.dataset_id == current_dataset.id
                            )
                        )
                    ).all()
                ),
                default=0,
            )
            + 1
        )
        created = await SourceDocumentService(self.session).create(
            experiment_id=config.experiment_id,
            source=source,
            provenance=SourceProvenance(
                origin=SourceOrigin.MODEL_OUTPUT,
                iteration=iteration,
                parent_document_id=parent_document_id,
                metadata={
                    "run_id": run.id,
                    "model_id": run.model_id_actual,
                    "system_prompt_sha256": config.system_prompt.sha256,
                },
            ),
            auto_assign=False,
        )
        run.output_document_id = created.id
        await self.session.commit()
        return created


class ExecutionEngine:
    def __init__(self, database: Database, settings: Settings, runner: ModelRunner) -> None:
        self.database = database
        self.settings = settings
        self.runner = runner
        self.semaphore = asyncio.Semaphore(1)
        self.tasks: set[asyncio.Task[None]] = set()

    async def interrupt_stale(self) -> None:
        async with self.database.session_factory() as session:
            await session.execute(
                update(Run)
                .where(Run.status.in_(["queued", "running", "evaluating"]))
                .values(status="interrupted", completed_at=utcnow())
            )
            await session.execute(
                update(RunConfig)
                .where(RunConfig.status.in_(["queued", "running", "evaluating"]))
                .values(status="interrupted")
            )
            await session.commit()

    def enqueue(self, config_id: str) -> None:
        task = asyncio.create_task(self.execute(config_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def shutdown(self) -> None:
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

    async def execute(self, config_id: str) -> None:
        async with self.semaphore:
            async with self.database.session_factory() as session:
                config = await ExecutionService(session, self.settings).get_config(config_id)
                config.status = "running"
                session.add(
                    Event(run_config_id=config_id, event_type="run_config_started", payload_json={})
                )
                await session.commit()
                run_ids = [run.id for run in sorted(config.runs, key=lambda item: item.run_number)]
            failed = False
            evaluation_failed = False
            for run_id in run_ids:
                try:
                    evaluation_failed = not await self._execute_run(run_id) or evaluation_failed
                except asyncio.CancelledError:
                    raise
                except Exception:
                    failed = True
            async with self.database.session_factory() as session:
                config = await session.get(RunConfig, config_id)
                if config is not None:
                    config.status = (
                        "failed"
                        if failed
                        else "completed_with_eval_errors"
                        if evaluation_failed
                        else "completed"
                    )
                    session.add(
                        Event(
                            run_config_id=config_id,
                            event_type="run_config_finished",
                            payload_json={"status": config.status},
                        )
                    )
                    await session.commit()

    async def _execute_run(self, run_id: str) -> bool:
        async with self.database.session_factory() as session:
            run = await ExecutionService(session, self.settings).get_run(
                run_id, include_content=True
            )
            config = await ExecutionService(session, self.settings).get_config(run.run_config_id)
            run.status = "running"
            run.started_at = utcnow()
            config.status = "running"
            session.add(
                Event(
                    run_config_id=config.id,
                    run_id=run.id,
                    event_type="run_started",
                    payload_json={"run_number": run.run_number},
                )
            )
            await session.commit()
            model_config = config.model_config
            request = ModelRequest(
                model_id=model_config.model_id,
                project=self.settings.gcp_project or "",
                location=model_config.location,
                system_prompt=config.system_prompt.content,
                user_prompt=config.user_prompt,
                source_texts=tuple(item.content_text for item in run.documents),
                temperature=model_config.temperature,
                top_p=model_config.top_p,
                seed=model_config.seed,
                max_output_tokens=model_config.max_output_tokens,
                endpoint_type=str(model_config.extra_config_json.get("endpoint_type", "")),
            )
            config_id = config.id
            provider = model_config.provider
            region = model_config.location
        start = time.monotonic()
        deltas: list[str] = []
        pending_delta: list[str] = []
        pending_size = 0
        last_delta_persisted = start

        async def persist_delta(delta: str) -> None:
            async with self.database.session_factory() as session:
                session.add(
                    Event(
                        run_config_id=config_id,
                        run_id=run_id,
                        event_type="run_output_delta",
                        payload_json={"text_delta": delta},
                    )
                )
                await session.commit()

        response = None
        try:
            async with asyncio.timeout(self.settings.model_timeout_seconds):
                async for stream_event in self.runner.stream(request):
                    if stream_event.text_delta:
                        deltas.append(stream_event.text_delta)
                        pending_delta.append(stream_event.text_delta)
                        pending_size += len(stream_event.text_delta)
                        if pending_size >= 256 or time.monotonic() - last_delta_persisted >= 0.2:
                            await persist_delta("".join(pending_delta))
                            pending_delta.clear()
                            pending_size = 0
                            last_delta_persisted = time.monotonic()
                    if stream_event.response is not None:
                        response = stream_event.response
                if pending_delta:
                    await persist_delta("".join(pending_delta))
                    pending_delta.clear()
                if response is None:
                    raise RuntimeError("Model stream ended without a final response")
        except asyncio.CancelledError:
            if pending_delta:
                await asyncio.shield(persist_delta("".join(pending_delta)))
                pending_delta.clear()
            partial_text = "".join(deltas)
            if partial_text:
                async with self.database.session_factory() as session:
                    run = await session.get(Run, run_id)
                    if run is not None:
                        run.response_text = partial_text
                        session.add(
                            Event(
                                run_config_id=config_id,
                                run_id=run_id,
                                event_type="run_output_persisted",
                                payload_json={
                                    "model_duration_ms": int((time.monotonic() - start) * 1000),
                                    "partial": True,
                                    "total_tokens": None,
                                },
                            )
                        )
                    await session.commit()
            raise
        except Exception as error:
            if pending_delta:
                await persist_delta("".join(pending_delta))
                pending_delta.clear()
            partial_text = "".join(deltas)
            async with self.database.session_factory() as session:
                run = await session.get(Run, run_id)
                if run is not None:
                    run.status = "failed"
                    run.completed_at = utcnow()
                    run.duration_ms = int((time.monotonic() - start) * 1000)
                    run.error_type = type(error).__name__
                    run.response_text = partial_text or None
                    if isinstance(error, TimeoutError):
                        run.error_message = (
                            "Model execution timed out after the configured backend limit"
                        )
                    elif str(error).startswith("Install the backend model extra:"):
                        run.error_message = "ADK is not installed; install backend[model]"
                    else:
                        run.error_message = (
                            "Model execution failed; verify backend model access and configuration"
                        )
                    if partial_text:
                        session.add(
                            Event(
                                run_config_id=config_id,
                                run_id=run_id,
                                event_type="run_output_persisted",
                                payload_json={
                                    "model_duration_ms": int((time.monotonic() - start) * 1000),
                                    "partial": True,
                                    "total_tokens": None,
                                },
                            )
                        )
                    session.add(
                        Event(
                            run_config_id=config_id,
                            run_id=run_id,
                            event_type="run_failed",
                            payload_json={"error_type": run.error_type},
                        )
                    )
                await session.commit()
            raise
        async with self.database.session_factory() as session:
            run = await session.get(Run, run_id)
            if run is not None:
                run.status = "evaluating"
                config = await session.get(RunConfig, config_id)
                if config is not None:
                    config.status = "evaluating"
                run.model_id_actual = response.model_id_actual
                run.provider = provider
                run.region = region
                run.input_tokens = response.input_tokens
                run.output_tokens = response.output_tokens
                run.total_tokens = response.total_tokens
                run.request_id = response.request_id
                run.trace_id = response.trace_id
                run.response_text = response.text
                session.add(
                    Event(
                        run_config_id=config_id,
                        run_id=run_id,
                        event_type="run_output_persisted",
                        payload_json={
                            "model_duration_ms": int((time.monotonic() - start) * 1000),
                            "total_tokens": run.total_tokens,
                        },
                    )
                )
                await session.commit()
        evaluation_errors: list[str] = []
        try:
            async with self.database.session_factory() as session:
                await EvaluationService(session).evaluate_run(run_id)
        except Exception as error:
            evaluation_errors.append("Deterministic evaluation failed.")
            await self._record_evaluation_failure(
                config_id, run_id, "deterministic", error
            )

        evaluator_model_config_id = config.evaluation_model_config_id
        if evaluator_model_config_id:
            try:
                async with self.database.session_factory() as session:
                    evaluator_config = await session.get(
                        ModelConfig, evaluator_model_config_id
                    )
                    if evaluator_config is None:
                        raise RuntimeError("Configured evaluation model snapshot is missing")
                    async with asyncio.timeout(self.settings.model_timeout_seconds):
                        await EvaluationService(session).evaluate_run_with_model(
                            run_id,
                            evaluator_config,
                            self.runner,
                            self.settings.gcp_project or "",
                        )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                evaluation_errors.append("Model-based evaluation failed.")
                await self._record_evaluation_failure(config_id, run_id, "llm_judge", error)

        async with self.database.session_factory() as session:
            run = await session.get(Run, run_id)
            if run is not None:
                run.status = "completed"
                run.completed_at = utcnow()
                run.duration_ms = int((time.monotonic() - start) * 1000)
                run.evaluation_error = "; ".join(evaluation_errors) or None
                session.add(
                    Event(
                        run_config_id=config_id,
                        run_id=run_id,
                        event_type="run_completed",
                        payload_json={
                            "duration_ms": run.duration_ms,
                            "evaluation_errors": len(evaluation_errors),
                        },
                    )
                )
                await session.commit()
        return not evaluation_errors

    async def _record_evaluation_failure(
        self, config_id: str, run_id: str, evaluator_type: str, error: Exception
    ) -> None:
        async with self.database.session_factory() as session:
            run = await session.get(Run, run_id)
            if run is not None:
                run.evaluation_error = "Evaluation failed."
                session.add(
                    Event(
                        run_config_id=config_id,
                        run_id=run_id,
                        event_type="run_eval_failed",
                        payload_json={
                            "evaluator_type": evaluator_type,
                            "error_type": type(error).__name__,
                        },
                    )
                )
            await session.commit()
