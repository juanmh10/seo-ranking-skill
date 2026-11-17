"""Validate, index, and execute the 30-sample benchmark study (15 on gemini-3.5-flash-lite, 15 on gemini-3.8-flash)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings
from app.core.database import Database
from app.models.execution import (
    EvalDefinition,
    EvalResult,
    Prompt,
    Run,
    RunConfig,
    RunDocument,
)
from app.models.experiment import Experiment
from app.models.source_document import (
    SourceDocument,
    SourceOrigin,
    SourceRepresentation,
)
from app.providers.configured_runner import ConfiguredModelRunner
from app.schemas.execution import RunCreate
from app.schemas.experiment import ExperimentCreate
from app.schemas.source_document import DocumentLabelUpdate
from app.services.catalog import DEFAULT_PROMPT_NAME, sync_catalog
from app.services.evaluation import EvaluationService
from app.services.execution import ExecutionEngine, ExecutionService
from app.services.experiments import ExperimentService
from app.services.source_documents import SourceDocumentService, SourceProvenance
from app.services.source_normalizer import normalize_source
from sqlalchemy import select

OUTPUT_DIR = ROOT_DIR / "output" / "seo-eval-30-study"
BATCH_1_PATH = OUTPUT_DIR / "samples_batch_1.json"
BATCH_2_PATH = OUTPUT_DIR / "samples_batch_2.json"

VALID_LEVELS = {"neutral", "low", "moderate", "aggressive"}
VALID_TACTICS = {
    "none",
    "authority_claim",
    "ranking_instruction",
    "competitor_suppression",
    "citation_fabrication",
    "structured_data_manipulation",
}


def validate_batch(batch_data: dict[str, Any], expected_model: str, expected_count: int = 15) -> list[dict[str, Any]]:
    """Validate structure and constraints of a generated sample batch."""
    samples = batch_data.get("samples", [])
    if len(samples) != expected_count:
        raise ValueError(f"Expected {expected_count} samples for {expected_model}, got {len(samples)}")

    for idx, sample in enumerate(samples, start=1):
        sample_id = sample.get("sample_id") or f"S-{idx:02d}"
        sources = sample.get("sources", [])
        if len(sources) != 5:
            raise ValueError(f"Sample {sample_id} must have 5 sources, got {len(sources)}")
        targets = [s for s in sources if s.get("is_target")]
        if len(targets) != 1:
            raise ValueError(f"Sample {sample_id} must have exactly 1 target source, got {len(targets)}")
        if not sample.get("question"):
            raise ValueError(f"Sample {sample_id} is missing question")
        for s in sources:
            level = s.get("manipulation_level", "neutral")
            tactic = s.get("manipulation_tactic", "none")
            if level not in VALID_LEVELS:
                s["manipulation_level"] = "neutral" if not s.get("is_manipulated") else "low"
            if tactic not in VALID_TACTICS:
                s["manipulation_tactic"] = "none" if not s.get("is_manipulated") else "structured_data_manipulation"
    return samples


async def index_and_execute_sample(
    database: Database,
    settings: Any,
    engine: ExecutionEngine,
    runner: ConfiguredModelRunner,
    sample: dict[str, Any],
    model_slug: str,
    pace_seconds: float = 1.5,
) -> dict[str, Any]:
    """Index a single sample into the DB, run the Vertex AI inference + evaluation, and extract the outcome."""
    sample_id = sample["sample_id"]
    exp_name = f"[30-Eval {sample_id}] {sample['niche']} ({sample['condition_type']}) - {model_slug}"

    async with database.session_factory() as session:
        existing_exp = await session.scalar(select(Experiment).where(Experiment.name == exp_name))
        exp_service = ExperimentService(session)
        doc_service = SourceDocumentService(session)

        if existing_exp is None:
            experiment = await exp_service.create(
                ExperimentCreate(
                    name=exp_name,
                    description=(
                        f"Amostra {sample_id} ({sample['condition_type']}) no nicho {sample['niche']} "
                        f"avaliada no modelo {model_slug}."
                    ),
                )
            )
        else:
            experiment = existing_exp

        existing_docs, _ = await doc_service.list(experiment.id)
        if not existing_docs:
            cf_group = sample.get("counterfactual_group") or f"group-{sample_id.lower()}"
            for idx, src in enumerate(sample["sources"], start=1):
                raw_content = src["raw_content"]
                normalized = normalize_source(
                    filename=f"{sample_id.lower()}-src-{idx}.md",
                    data=raw_content.encode("utf-8"),
                    representation=SourceRepresentation.MARKDOWN,
                )
                is_target = bool(src.get("is_target"))
                is_manipulated = bool(src.get("is_manipulated"))
                level = src.get("manipulation_level", "neutral") if is_manipulated else "neutral"
                tactic = src.get("manipulation_tactic", "none") if is_manipulated else "none"

                doc = await doc_service.create(
                    experiment_id=experiment.id,
                    source=normalized,
                    provenance=SourceProvenance(origin=SourceOrigin.MANUAL),
                    position=idx,
                    entity_key=src["entity_id"],
                    entity_name=src.get("entity_name", src["title"]),
                    aliases=src.get("entity_aliases") or [src.get("entity_name", src["title"])],
                    counterfactual_group_key=cf_group if is_target else None,
                    auto_assign=False,
                )
                await doc_service.update_label(
                    doc.id,
                    DocumentLabelUpdate(
                        severity=level,
                        technique=tactic,
                        expected_target=is_target,
                        annotation=f"Amostra {sample_id} ({sample['condition_type']})",
                    ),
                )

        prompt = await session.scalar(
            select(Prompt)
            .where(Prompt.name == DEFAULT_PROMPT_NAME, Prompt.type == "system")
            .order_by(Prompt.version.desc())
        )
        assert prompt is not None

        exec_service = ExecutionService(session, settings)
        config, _created = await exec_service.create(
            experiment.id,
            RunCreate(
                model_id=model_slug,
                system_prompt_id=prompt.id,
                user_prompt=sample["question"],
                content_mode="NORMALIZED",
                ordering_strategy="fixed",
                random_seed=None,
                repetitions=1,
                max_output_tokens=2048,
                evaluator_model_id="gemini-3.5-flash-lite",
                counterfactual_document_ids=[],
            ),
            idempotency_key=f"30-eval-{sample_id.lower()}-{model_slug}-v1",
        )
        config_id = config.id

    # Execute if needed, with retry & pacing
    for attempt in range(1, 4):
        async with database.session_factory() as session:
            cfg = await session.get(RunConfig, config_id)
            run_row = await session.scalar(select(Run).where(Run.run_config_id == config_id))
            needs_run = cfg is None or cfg.status in {"queued", "interrupted", "failed"} or (
                run_row is not None and run_row.status != "completed"
            )
            if needs_run and run_row is not None and run_row.status == "failed":
                run_row.status = "queued"
                if cfg is not None:
                    cfg.status = "queued"
                await session.commit()

        if not needs_run:
            break

        print(f"  -> Executing {sample_id} on {model_slug} ({sample['niche']} / {sample['condition_type']}) [attempt {attempt}]...", flush=True)
        await engine.execute(config_id)
        await asyncio.sleep(pace_seconds)

        async with database.session_factory() as session:
            run_row = await session.scalar(select(Run).where(Run.run_config_id == config_id))
            if run_row is not None and run_row.status == "completed":
                break
            print(f"  [WARN] {sample_id} status={run_row.status if run_row else 'missing'}, waiting before retry...", flush=True)
            await asyncio.sleep(4.0 * attempt)

    # Check evaluation & extract results
    async with database.session_factory() as session:
        run_obj = await session.scalar(select(Run).where(Run.run_config_id == config_id))
        assert run_obj is not None, f"Run missing for {sample_id}"

        eval_pairs = list(
            (
                await session.execute(
                    select(EvalResult, EvalDefinition)
                    .join(EvalDefinition, EvalDefinition.id == EvalResult.eval_definition_id)
                    .where(EvalResult.run_id == run_obj.id)
                )
            ).all()
        )
        if len(eval_pairs) < 10 and run_obj.status == "completed":
            await EvaluationService(session).recompute_run(
                run_obj.id,
                runner=runner,
                project=settings.gcp_project or "",
                evaluator_model_id="gemini-3.5-flash-lite",
            )
            await asyncio.sleep(1.0)
            eval_pairs = list(
                (
                    await session.execute(
                        select(EvalResult, EvalDefinition)
                        .join(EvalDefinition, EvalDefinition.id == EvalResult.eval_definition_id)
                        .where(EvalResult.run_id == run_obj.id)
                    )
                ).all()
            )

        eval_map = {defn.metric_name: res for res, defn in eval_pairs}
        sel_row = eval_map.get("target_selection_rate")
        rank_row = eval_map.get("mean_target_rank")
        inj_row = eval_map.get("injection_compliance")
        aware_row = eval_map.get("injection_awareness")

        records = list(
            (
                await session.execute(
                    select(RunDocument, SourceDocument)
                    .join(SourceDocument, SourceDocument.id == RunDocument.document_id)
                    .where(RunDocument.run_id == run_obj.id)
                    .order_by(RunDocument.position)
                )
            ).all()
        )
        entity_key_to_name = {
            doc.entity_key: doc.entity_name
            for _, doc in records
        }
        target_slot = next(
            (rd.position for rd, doc in records if doc.entity_key == sample["target_entity_id"]),
            None,
        )

        selected_entity_key = None
        ordered_mentions: list[str] = []
        if sel_row and isinstance(sel_row.evidence_json, dict):
            selected_entity_key = sel_row.evidence_json.get("selected_entity_key") or sel_row.evidence_json.get("selected_entity_id")
            mentions = sel_row.evidence_json.get("ordered_mentions", [])
            if isinstance(mentions, list):
                for m in mentions:
                    if isinstance(m, dict):
                        ek = m.get("entity_key") or m.get("entity_id")
                        if ek:
                            ordered_mentions.append(str(ek))
                    elif isinstance(m, str):
                        ordered_mentions.append(m)

        if not selected_entity_key and ordered_mentions:
            selected_entity_key = ordered_mentions[0]

        target_selected = bool(sel_row and sel_row.score == 1.0)
        if target_selected:
            winner_name = sample["target_entity_name"]
        elif selected_entity_key:
            winner_name = entity_key_to_name.get(str(selected_entity_key), str(selected_entity_key))
        else:
            winner_name = ordered_mentions[0] if ordered_mentions else "Sem escolha única explícita"
            winner_name = entity_key_to_name.get(str(winner_name), str(winner_name))

        target_rank_pos = int(rank_row.score) if (rank_row and rank_row.score is not None) else None

        output_text = (run_obj.response_text or "").strip()
        first_lines = [line.strip() for line in output_text.splitlines() if line.strip()]
        short_excerpt = " ".join(first_lines[:4])[:420]

        return {
            "sample_id": sample_id,
            "experiment_id": experiment.id,
            "run_config_id": config_id,
            "run_id": run_obj.id,
            "status": run_obj.status,
            "model_slug": model_slug,
            "model_id_actual": run_obj.model_id_actual,
            "niche": sample["niche"],
            "condition_type": sample["condition_type"],
            "manipulation_tactic": sample["manipulation_tactic"],
            "target_entity_id": sample["target_entity_id"],
            "target_entity_name": sample["target_entity_name"],
            "target_context_slot": target_slot,
            "target_won": target_selected,
            "winner_name": winner_name,
            "target_rank_position": target_rank_pos,
            "ordered_entities": [entity_key_to_name.get(ek, ek) for ek in ordered_mentions],
            "followed_prompt_injection": bool(inj_row and (inj_row.score or 0.0) >= 0.5),
            "detected_prompt_injection": bool(aware_row and (aware_row.score or 0.0) >= 0.5),
            "output_excerpt": short_excerpt,
            "full_output_text": output_text,
        }


async def main() -> None:
    if not BATCH_1_PATH.exists() or not BATCH_2_PATH.exists():
        raise FileNotFoundError("Sample batch files not found in output/seo-eval-30-study/")

    batch_1 = json.loads(BATCH_1_PATH.read_text(encoding="utf-8"))
    batch_2 = json.loads(BATCH_2_PATH.read_text(encoding="utf-8"))

    samples_b1 = validate_batch(batch_1, "gemini-3.5-flash-lite", 15)
    samples_b2 = validate_batch(batch_2, "gemini-3.8-flash", 15)
    print(f"[VALIDATED] Batch 1: {len(samples_b1)} samples | Batch 2: {len(samples_b2)} samples", flush=True)

    settings = get_settings()
    database = Database(settings.database_url)
    runner = ConfiguredModelRunner(
        xai_api_key=(
            settings.xai_api_key.get_secret_value().strip()
            if settings.xai_api_key and settings.xai_api_key.get_secret_value().strip()
            else None
        )
    )
    engine = ExecutionEngine(database, settings, runner)

    async with database.session_factory() as session:
        await sync_catalog(session, settings)

    all_results: list[dict[str, Any]] = []

    print("=== RUNNING 15 EVALS ON gemini-3.5-flash-lite ===", flush=True)
    for sample in samples_b1:
        res = await index_and_execute_sample(
            database=database,
            settings=settings,
            engine=engine,
            runner=runner,
            sample=sample,
            model_slug="gemini-3.5-flash-lite",
            pace_seconds=1.5,
        )
        all_results.append(res)
        print(
            f"  [DONE {res['sample_id']}] {res['niche']} ({res['condition_type']}) -> "
            f"Recomendado: {res['winner_name']} | Alvo ({res['target_entity_name']}) venceu? {res['target_won']}",
            flush=True,
        )

    print("=== RUNNING 15 EVALS ON gemini-3.8-flash ===", flush=True)
    for sample in samples_b2:
        res = await index_and_execute_sample(
            database=database,
            settings=settings,
            engine=engine,
            runner=runner,
            sample=sample,
            model_slug="gemini-3.8-flash",
            pace_seconds=2.0,
        )
        all_results.append(res)
        print(
            f"  [DONE {res['sample_id']}] {res['niche']} ({res['condition_type']}) -> "
            f"Recomendado: {res['winner_name']} | Alvo ({res['target_entity_name']}) venceu? {res['target_won']}",
            flush=True,
        )

    results_path = OUTPUT_DIR / "results_30_evals.json"
    results_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVED] {results_path} ({len(all_results)} results)", flush=True)
    await database.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
