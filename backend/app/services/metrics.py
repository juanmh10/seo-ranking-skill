from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.execution import EvalResult, ModelConfig, Prompt, Run, RunConfig, RunDocument
from app.models.source_document import SourceDocument
from app.schemas.execution import (
    ExperimentMetricsRead,
    ManipulationConditionRead,
    ManipulationLiftComparisonRead,
    ManipulationLiftStatus,
    MetricConditionRead,
)


@dataclass(frozen=True)
class _LiftRun:
    run_config_id: str
    dataset_id: str
    run_number: int
    status: str
    target_document_id: str
    target_severity: str
    target_technique: str
    target_position: int
    target_mime_type: str
    counterfactual_group_key: str | None
    entity_key: str | None
    model_id: str
    selection_score: float | None
    target_rank: float | None
    other_context_signature: tuple[tuple[int, str, str], ...]


def _latest_run_evaluations(results: list[EvalResult]) -> list[EvalResult]:
    latest: dict[str, EvalResult] = {}
    for result in results:
        metric_name = result.definition.metric_name
        previous = latest.get(metric_name)
        if previous is None or result.definition.version > previous.definition.version:
            latest[metric_name] = result
    return list(latest.values())


class MetricsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def experiment(self, experiment_id: str) -> ExperimentMetricsRead:
        statement = (
            select(Run, RunConfig, ModelConfig, Prompt)
            .join(RunConfig, RunConfig.id == Run.run_config_id)
            .join(ModelConfig, ModelConfig.id == RunConfig.model_config_id)
            .join(Prompt, Prompt.id == RunConfig.system_prompt_id)
            .where(RunConfig.experiment_id == experiment_id)
            .options(
                selectinload(Run.documents).defer(RunDocument.content_text),
                selectinload(Run.eval_results).joinedload(EvalResult.definition),
            )
            .order_by(Run.created_at)
        )
        rows = list((await self.session.execute(statement)).all())
        all_document_ids = {
            run_document.document_id for run, _, _, _ in rows for run_document in run.documents
        }
        source_metadata: dict[str, tuple[str, str | None, str | None, str | None]] = {}
        if all_document_ids:
            source_rows = await self.session.execute(
                select(
                    SourceDocument.id,
                    SourceDocument.mime_type,
                    SourceDocument.entity_key,
                    SourceDocument.lineage_id,
                    SourceDocument.counterfactual_group_key,
                ).where(SourceDocument.id.in_(all_document_ids))
            )
            source_metadata = {
                row.id: (
                    row.mime_type,
                    row.entity_key,
                    row.lineage_id,
                    row.counterfactual_group_key,
                )
                for row in source_rows
            }

        aggregates: dict[tuple[object, ...], dict[str, object]] = {}
        lift_runs_by_config: dict[str, list[_LiftRun]] = {}
        repetitions_by_config: dict[str, int] = {}
        completed_runs = 0
        evaluated_runs = 0
        for run, config, model, prompt in rows:
            latest_evaluations = _latest_run_evaluations(run.eval_results)
            if run.status == "completed":
                completed_runs += 1
                if latest_evaluations:
                    evaluated_runs += 1
            target_entries = [
                item
                for item in run.documents
                if bool(item.label_snapshot_json.get("expected_target"))
            ]
            if len(target_entries) != 1:
                continue
            target_document = target_entries[0]
            target_label = target_document.label_snapshot_json
            metadata = source_metadata.get(
                target_document.document_id, ("unknown", None, None, None)
            )
            severity = str(target_label.get("severity", "unknown"))
            technique = str(target_label.get("technique", "unknown"))
            selection_score = next(
                (
                    result.score
                    for result in latest_evaluations
                    if result.definition.metric_name == "target_selection_rate"
                ),
                None,
            )
            target_rank = next(
                (
                    result.score
                    for result in latest_evaluations
                    if result.definition.metric_name == "target_rank"
                ),
                None,
            )
            other_context_signature = tuple(
                sorted(
                    (item.position, item.document_id, item.content_sha256)
                    for item in run.documents
                    if item is not target_document
                )
            )
            lift_runs_by_config.setdefault(config.id, []).append(
                _LiftRun(
                    run_config_id=config.id,
                    dataset_id=config.dataset_id,
                    run_number=run.run_number,
                    status=run.status,
                    target_document_id=target_document.document_id,
                    target_severity=severity,
                    target_technique=technique,
                    target_position=target_document.position,
                    target_mime_type=metadata[0],
                    counterfactual_group_key=metadata[3],
                    entity_key=metadata[1],
                    model_id=run.model_id_actual or model.model_id,
                    selection_score=selection_score,
                    target_rank=target_rank,
                    other_context_signature=other_context_signature,
                )
            )
            repetitions_by_config[config.id] = config.repetitions

            if run.status != "completed":
                continue
            user_hash = hashlib.sha256(config.user_prompt.encode("utf-8")).hexdigest()
            key = (
                config.dataset_id,
                run.model_id_actual or model.model_id,
                model.provider,
                model.location,
                prompt.version,
                prompt.sha256,
                user_hash,
                config.content_mode,
                config.ordering_strategy,
                config.random_seed,
                model.temperature,
                model.top_p,
                model.seed,
                model.max_output_tokens,
                severity,
                technique,
                target_document.position,
                metadata[0],
                metadata[3],
            )
            bucket = aggregates.setdefault(
                key,
                {
                    "run_count": 0,
                    "selection_scores": [],
                    "rank_scores": [],
                    "metric_scores": {},
                },
            )
            bucket["run_count"] = int(bucket["run_count"]) + 1
            for result in latest_evaluations:
                metric_name = result.definition.metric_name
                if result.score is not None:
                    metric_scores = bucket["metric_scores"]
                    assert isinstance(metric_scores, dict)
                    metric_scores.setdefault(metric_name, []).append(result.score)
                if metric_name == "target_selection_rate" and result.score is not None:
                    bucket["selection_scores"].append(result.score)  # type: ignore[union-attr]
                elif metric_name == "target_rank" and result.score is not None:
                    bucket["rank_scores"].append(result.score)  # type: ignore[union-attr]

        conditions: list[MetricConditionRead] = []
        for key, values in aggregates.items():
            selection_scores = values["selection_scores"]
            rank_scores = values["rank_scores"]
            metric_scores = values["metric_scores"]
            assert isinstance(metric_scores, dict)
            conditions.append(
                MetricConditionRead(
                    dataset_id=str(key[0]),
                    model_id=str(key[1]),
                    provider=str(key[2]),
                    location=str(key[3]),
                    system_prompt_version=int(key[4]),
                    system_prompt_sha256=str(key[5]),
                    user_prompt_sha256=str(key[6]),
                    content_mode=str(key[7]),
                    ordering_strategy=str(key[8]),
                    random_seed=key[9] if isinstance(key[9], int) else None,
                    temperature=key[10] if isinstance(key[10], float) else None,
                    top_p=key[11] if isinstance(key[11], float) else None,
                    generation_seed=key[12] if isinstance(key[12], int) else None,
                    max_output_tokens=int(key[13]),
                    target_severity=str(key[14]),
                    target_technique=str(key[15]),
                    target_position=int(key[16]),
                    target_mime_type=str(key[17]),
                    counterfactual_group_key=(str(key[18]) if key[18] is not None else None),
                    run_count=int(values["run_count"]),
                    selection_sample_count=len(selection_scores),
                    target_selection_rate=(
                        sum(selection_scores) / len(selection_scores) if selection_scores else None
                    ),
                    rank_sample_count=len(rank_scores),
                    mean_target_rank=(sum(rank_scores) / len(rank_scores) if rank_scores else None),
                    metric_sample_counts={
                        str(name): len(scores) for name, scores in metric_scores.items()
                    },
                    metric_means={
                        str(name): sum(scores) / len(scores)
                        for name, scores in metric_scores.items()
                        if scores
                    },
                )
            )

        comparisons, lift_reason = self._calculate_lift(lift_runs_by_config, repetitions_by_config)
        return ExperimentMetricsRead(
            experiment_id=experiment_id,
            total_runs=len(rows),
            completed_runs=completed_runs,
            evaluated_runs=evaluated_runs,
            conditions=sorted(
                conditions,
                key=lambda item: (
                    item.model_id,
                    item.target_severity,
                    item.target_technique,
                    item.target_position,
                ),
            ),
            manipulation_lift=ManipulationLiftStatus(
                calculable=bool(comparisons),
                reason=None if comparisons else lift_reason,
                comparisons=comparisons,
            ),
        )

    @staticmethod
    def _calculate_lift(
        runs_by_config: dict[str, list[_LiftRun]], repetitions_by_config: dict[str, int]
    ) -> tuple[list[ManipulationLiftComparisonRead], str]:
        comparisons: list[ManipulationLiftComparisonRead] = []
        saw_multiple_conditions = False
        for config_id, unsorted_runs in runs_by_config.items():
            runs = sorted(unsorted_runs, key=lambda item: item.run_number)
            target_ids = list(dict.fromkeys(item.target_document_id for item in runs))
            scenario_count = len(target_ids)
            if scenario_count < 2:
                continue
            saw_multiple_conditions = True
            repetitions = repetitions_by_config[config_id]
            if len(runs) != scenario_count * repetitions:
                continue
            scenario_order = [item.target_document_id for item in runs[:scenario_count]]
            if len(set(scenario_order)) != scenario_count:
                continue
            if any(
                item.target_document_id != scenario_order[(item.run_number - 1) % scenario_count]
                for item in runs
            ):
                continue

            by_repetition_and_target = {
                ((item.run_number - 1) // scenario_count, item.target_document_id): item
                for item in runs
            }
            conditions_by_target = {item.target_document_id: item for item in runs[:scenario_count]}
            controls = [
                item
                for item in conditions_by_target.values()
                if item.target_severity == "neutral" and item.target_technique == "none"
            ]
            if len(controls) != 1:
                continue
            control = controls[0]
            for injected in conditions_by_target.values():
                if injected.target_document_id == control.target_document_id:
                    continue
                group_key = control.counterfactual_group_key
                if (
                    not group_key
                    or injected.counterfactual_group_key != group_key
                    or not control.entity_key
                    or injected.entity_key != control.entity_key
                    or injected.target_mime_type != control.target_mime_type
                ):
                    continue

                matched: list[tuple[float, float, int, float | None]] = []
                for repetition in range(repetitions):
                    control_run = by_repetition_and_target.get(
                        (repetition, control.target_document_id)
                    )
                    injected_run = by_repetition_and_target.get(
                        (repetition, injected.target_document_id)
                    )
                    if (
                        control_run is None
                        or injected_run is None
                        or control_run.status != "completed"
                        or injected_run.status != "completed"
                        or control_run.selection_score is None
                        or injected_run.selection_score is None
                        or control_run.model_id != injected_run.model_id
                        or control_run.target_position != injected_run.target_position
                        or control_run.target_mime_type != injected_run.target_mime_type
                        or control_run.other_context_signature
                        != injected_run.other_context_signature
                    ):
                        continue
                    matched.append(
                        (
                            control_run.selection_score,
                            injected_run.selection_score,
                            control_run.target_position,
                            (
                                control_run.target_rank - injected_run.target_rank
                                if control_run.target_rank is not None
                                and injected_run.target_rank is not None
                                else None
                            ),
                        )
                    )
                if not matched:
                    continue

                control_rate = sum(item[0] for item in matched) / len(matched)
                injected_rate = sum(item[1] for item in matched) / len(matched)
                lift = injected_rate - control_rate
                rank_deltas = [item[3] for item in matched if item[3] is not None]
                position_distribution: dict[str, int] = {}
                for _, _, position, _ in matched:
                    position_key = str(position)
                    position_distribution[position_key] = (
                        position_distribution.get(position_key, 0) + 1
                    )
                comparisons.append(
                    ManipulationLiftComparisonRead(
                        run_config_id=config_id,
                        dataset_id=control.dataset_id,
                        counterfactual_group_key=group_key,
                        model_id=control.model_id,
                        control=ManipulationConditionRead(
                            severity=control.target_severity,
                            technique=control.target_technique,
                        ),
                        injected=ManipulationConditionRead(
                            severity=injected.target_severity,
                            technique=injected.target_technique,
                        ),
                        control_selection_rate=control_rate,
                        injected_selection_rate=injected_rate,
                        lift=lift,
                        lift_percentage_points=lift * 100,
                        rank_delta=(sum(rank_deltas) / len(rank_deltas) if rank_deltas else None),
                        rank_delta_sample_count=len(rank_deltas),
                        matched_pair_count=len(matched),
                        position_distribution=position_distribution,
                    )
                )

        if comparisons:
            return comparisons, ""
        if saw_multiple_conditions:
            return [], (
                "Counterfactual variants exist, but no completed, scored pair matched on target "
                "position and the other four source snapshots."
            )
        return [], (
            "Add one neutral/none control and at least one manipulated target variant in the same "
            "counterfactual group, then run both conditions."
        )
