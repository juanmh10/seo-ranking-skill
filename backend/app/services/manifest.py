from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.execution import EvalDefinition, EvalResult, Event, Prompt, Run, RunConfig
from app.models.experiment import Dataset, Experiment
from app.models.source_document import SourceDocument


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


class ManifestService:
    """Build a self-contained, read-only export of an experiment's recorded state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(self, experiment_id: str) -> dict[str, object]:
        experiment = await self.session.get(Experiment, experiment_id)
        if experiment is None:
            raise LookupError("Experiment not found")

        datasets = list(
            (
                await self.session.scalars(
                    select(Dataset)
                    .where(Dataset.experiment_id == experiment_id)
                    .options(selectinload(Dataset.documents).selectinload(SourceDocument.label))
                    .order_by(Dataset.version)
                )
            ).all()
        )
        configs = list(
            (
                await self.session.scalars(
                    select(RunConfig)
                    .where(RunConfig.experiment_id == experiment_id)
                    .options(
                        selectinload(RunConfig.model_config),
                        selectinload(RunConfig.evaluation_model_config),
                        selectinload(RunConfig.system_prompt),
                        selectinload(RunConfig.runs).selectinload(Run.documents),
                        selectinload(RunConfig.runs)
                        .selectinload(Run.eval_results)
                        .joinedload(EvalResult.definition),
                    )
                    .order_by(RunConfig.created_at, RunConfig.id)
                )
            ).all()
        )
        definitions = list(
            (
                await self.session.scalars(
                    select(EvalDefinition).order_by(
                        EvalDefinition.metric_name, EvalDefinition.version
                    )
                )
            ).all()
        )
        evaluation_prompts = list(
            (
                await self.session.scalars(
                    select(Prompt)
                    .where(Prompt.type == "evaluation")
                    .order_by(Prompt.name, Prompt.version)
                )
            ).all()
        )
        config_ids = [config.id for config in configs]
        events: list[Event] = []
        if config_ids:
            events = list(
                (
                    await self.session.scalars(
                        select(Event)
                        .where(Event.run_config_id.in_(config_ids))
                        .order_by(Event.id)
                    )
                ).all()
            )

        content_blobs: dict[str, str] = {}
        for dataset in datasets:
            for document in dataset.documents:
                self._content_ref(document.raw_content, content_blobs)
                self._content_ref(document.normalized_content, content_blobs)
        for config in configs:
            for run in config.runs:
                for document in run.documents:
                    self._content_ref(document.content_text, content_blobs)

        return {
            "schema_version": "1.0",
            "exported_at": _timestamp(datetime.now(UTC)),
            "experiment": {
                "id": experiment.id,
                "name": experiment.name,
                "description": experiment.description,
                "status": experiment.status,
                "created_at": _timestamp(experiment.created_at),
                "updated_at": _timestamp(experiment.updated_at),
            },
            "datasets": [self._dataset(dataset, content_blobs) for dataset in datasets],
            "content_blobs": content_blobs,
            "eval_suite": [
                {
                    "id": definition.id,
                    "name": definition.name,
                    "version": definition.version,
                    "evaluator_type": definition.evaluator_type,
                    "metric_name": definition.metric_name,
                    "description": definition.description,
                    "config": definition.config_json,
                    "prompt_id": definition.prompt_id,
                    "created_at": _timestamp(definition.created_at),
                }
                for definition in definitions
            ],
            "evaluation_prompts": [
                {
                    "id": prompt.id,
                    "name": prompt.name,
                    "version": prompt.version,
                    "sha256": prompt.sha256,
                    "content": prompt.content,
                }
                for prompt in evaluation_prompts
            ],
            "run_configs": [self._run_config(config, content_blobs) for config in configs],
            "events": [
                {
                    "id": event.id,
                    "run_config_id": event.run_config_id,
                    "run_id": event.run_id,
                    "type": event.event_type,
                    "payload": event.payload_json,
                    "created_at": _timestamp(event.created_at),
                }
                for event in events
            ],
        }

    @staticmethod
    def _content_ref(content: str, blobs: dict[str, str]) -> str:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        blobs.setdefault(digest, content)
        return digest

    @staticmethod
    def _dataset(dataset: Dataset, content_blobs: dict[str, str]) -> dict[str, object]:
        return {
            "id": dataset.id,
            "name": dataset.name,
            "version": dataset.version,
            "status": dataset.status,
            "created_at": _timestamp(dataset.created_at),
            "documents": [
                {
                    "id": document.id,
                    "lineage_id": document.lineage_id,
                    "parent_document_id": document.parent_document_id,
                    "filename": document.filename,
                    "mime_type": document.mime_type,
                    "content_type": document.content_type,
                    "source_representation": document.source_representation,
                    "origin": document.origin,
                    "sha256": document.sha256,
                    "byte_size": document.byte_size,
                    "raw_content_sha256": ManifestService._content_ref(
                        document.raw_content, content_blobs
                    ),
                    "normalized_content_sha256": ManifestService._content_ref(
                        document.normalized_content, content_blobs
                    ),
                    "position": document.position,
                    "iteration": document.iteration,
                    "entity_key": document.entity_key,
                    "entity_name": document.entity_name,
                    "aliases": document.aliases_json,
                    "counterfactual_group_key": document.counterfactual_group_key,
                    "metadata": document.metadata_json,
                    "normalizer_version": document.metadata_json.get("normalizer_version"),
                    "label": (
                        {
                            "severity": document.label.severity,
                            "technique": document.label.technique,
                            "expected_target": document.label.expected_target,
                            "annotation": document.label.annotation,
                            "annotator": document.label.annotator,
                        }
                        if document.label
                        else None
                    ),
                    "created_at": _timestamp(document.created_at),
                }
                for document in sorted(
                    dataset.documents,
                    key=lambda item: (
                        item.position is None,
                        item.position or 0,
                        item.created_at,
                        item.id,
                    ),
                )
            ],
        }

    @staticmethod
    def _run_config(
        config: RunConfig, content_blobs: dict[str, str]
    ) -> dict[str, object]:
        model = config.model_config
        prompt = config.system_prompt
        return {
            "id": config.id,
            "dataset_id": config.dataset_id,
            "status": config.status,
            "created_at": _timestamp(config.created_at),
            "request_sha256": config.request_sha256,
            "model": {
                "provider": model.provider,
                "model_id": model.model_id,
                "display_name": model.display_name,
                "location": model.location,
                "endpoint_type": model.extra_config_json.get("endpoint_type"),
                "generation_config": {
                    "temperature": model.temperature,
                    "top_p": model.top_p,
                    "seed": model.seed,
                    "max_output_tokens": model.max_output_tokens,
                    "thinking": model.thinking_config_json,
                },
            },
            "system_prompt": {
                "id": prompt.id,
                "name": prompt.name,
                "version": prompt.version,
                "sha256": prompt.sha256,
                "content": prompt.content,
            },
            "evaluation_model": (
                {
                    "provider": config.evaluation_model_config.provider,
                    "model_id": config.evaluation_model_config.model_id,
                    "display_name": config.evaluation_model_config.display_name,
                    "location": config.evaluation_model_config.location,
                    "generation_config": {
                        "temperature": config.evaluation_model_config.temperature,
                        "top_p": config.evaluation_model_config.top_p,
                        "seed": config.evaluation_model_config.seed,
                        "max_output_tokens": config.evaluation_model_config.max_output_tokens,
                    },
                }
                if config.evaluation_model_config
                else None
            ),
            "user_prompt": config.user_prompt,
            "content_mode": config.content_mode,
            "ordering_strategy": config.ordering_strategy,
            "random_seed": config.random_seed,
            "repetitions": config.repetitions,
            "runs": [
                ManifestService._run(run, content_blobs)
                for run in sorted(config.runs, key=lambda item: item.run_number)
            ],
        }

    @staticmethod
    def _run(run: Run, content_blobs: dict[str, str]) -> dict[str, object]:
        return {
            "id": run.id,
            "run_number": run.run_number,
            "status": run.status,
            "started_at": _timestamp(run.started_at),
            "completed_at": _timestamp(run.completed_at),
            "duration_ms": run.duration_ms,
            "model_id_actual": run.model_id_actual,
            "provider": run.provider,
            "region": run.region,
            "token_usage": {
                "input": run.input_tokens,
                "output": run.output_tokens,
                "total": run.total_tokens,
            },
            "request_id": run.request_id,
            "trace_id": run.trace_id,
            "response_text": run.response_text,
            "error_type": run.error_type,
            "error_message": run.error_message,
            "evaluation_error": run.evaluation_error,
            "sources": [
                {
                    "document_id": document.document_id,
                    "position": document.position,
                    "content_sha256": document.content_sha256,
                    "tokens_estimated": document.tokens_estimated,
                    "content_blob_sha256": ManifestService._content_ref(
                        document.content_text, content_blobs
                    ),
                    "label_snapshot": document.label_snapshot_json,
                }
                for document in sorted(run.documents, key=lambda item: item.position)
            ],
            "eval_results": [
                {
                    "definition": {
                        "id": result.definition.id,
                        "metric_name": result.definition.metric_name,
                        "version": result.definition.version,
                        "evaluator_type": result.definition.evaluator_type,
                    },
                    "score": result.score,
                    "passed": result.passed,
                    "label": result.label,
                    "reasoning": result.reasoning,
                    "evidence": result.evidence_json,
                    "raw_result": result.raw_result_json,
                    "evaluator_model": result.evaluator_model,
                    "evaluator_version": result.evaluator_version,
                    "created_at": _timestamp(result.created_at),
                }
                for result in sorted(
                    run.eval_results,
                    key=lambda item: (item.definition.metric_name, item.definition.version),
                )
            ],
        }
