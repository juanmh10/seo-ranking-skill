from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.experiment import Dataset, DatasetStatus, Experiment
from app.models.source_document import DocumentLabel, SourceDocument
from app.schemas.sample_packs import SamplePackRead
from app.services.source_normalizer import normalize_source

SAMPLE_PACKS_ROOT = Path(__file__).resolve().parents[3] / "examples" / "sample_packs"
SAMPLE_PACK_ID = "veterinary-recommendation"


class SamplePackNotFoundError(LookupError):
    pass


class SamplePackConflictError(ValueError):
    pass


@dataclass(frozen=True)
class SamplePack:
    summary: SamplePackRead
    documents: tuple[dict[str, Any], ...]


def get_sample_pack(sample_pack_id: str) -> SamplePack:
    if sample_pack_id != SAMPLE_PACK_ID:
        raise SamplePackNotFoundError("Sample pack not found")

    root = SAMPLE_PACKS_ROOT / SAMPLE_PACK_ID
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Configured sample pack is invalid") from error

    if manifest.get("id") != SAMPLE_PACK_ID:
        raise RuntimeError("Configured sample pack ID does not match its manifest")
    document_specs = tuple(manifest.get("documents", ()))
    if len(document_specs) != 5:
        raise RuntimeError("Sample pack must contain exactly five documents")

    positions = [spec.get("position") for spec in document_specs]
    if sorted(positions) != [1, 2, 3, 4, 5]:
        raise RuntimeError("Sample pack positions must be the five unique source slots")

    summary = SamplePackRead(
        id=SAMPLE_PACK_ID,
        name=manifest["name"],
        description=manifest["description"],
        document_count=len(document_specs),
        recommended_question=manifest["recommended_question"],
    )
    return SamplePack(summary=summary, documents=document_specs)


async def list_sample_packs() -> list[SamplePackRead]:
    return [get_sample_pack(SAMPLE_PACK_ID).summary]


async def import_sample_pack(
    session: AsyncSession, experiment_id: str, sample_pack_id: str
) -> tuple[SamplePackRead, str, list[SourceDocument]]:
    pack = get_sample_pack(sample_pack_id)
    experiment = await session.get(Experiment, experiment_id)
    if experiment is None:
        raise SamplePackNotFoundError("Experiment not found")
    if experiment.status == "archived":
        raise SamplePackConflictError("Archived experiments cannot receive sources")

    dataset = await session.scalar(
        select(Dataset)
        .where(Dataset.experiment_id == experiment_id)
        .order_by(Dataset.version.desc())
        .limit(1)
    )
    if dataset is None:
        raise SamplePackNotFoundError("Experiment dataset not found")
    if dataset.status != DatasetStatus.DRAFT.value:
        raise SamplePackConflictError("A frozen dataset cannot receive a sample pack")

    document_count = await session.scalar(
        select(func.count(SourceDocument.id)).where(SourceDocument.dataset_id == dataset.id)
    )
    if document_count:
        raise SamplePackConflictError(
            "Load the sample pack into an empty dataset to avoid mixing or replacing sources"
        )

    documents: list[SourceDocument] = []
    for spec in pack.documents:
        filename = spec["filename"]
        try:
            content = (SAMPLE_PACKS_ROOT / SAMPLE_PACK_ID / filename).read_bytes()
        except OSError as error:
            raise RuntimeError("Configured sample pack document is missing") from error

        source = normalize_source(filename=filename, data=content)
        document_id = str(uuid.uuid4())
        label = DocumentLabel(
            severity=spec["severity"],
            technique=spec["technique"],
            expected_target=spec["expected_target"],
            annotation=spec["annotation"],
            annotator="sample-pack",
        )
        document = SourceDocument(
            id=document_id,
            lineage_id=document_id,
            dataset_id=dataset.id,
            filename=source.filename,
            mime_type=source.mime_type,
            content_type=source.content_type,
            source_representation=source.representation.value,
            origin="manual",
            sha256=source.sha256,
            byte_size=source.byte_size,
            raw_content=source.raw_content,
            normalized_content=source.normalized_content,
            position=spec["position"],
            iteration=0,
            entity_key=spec["entity_key"],
            entity_name=spec["entity_name"],
            aliases_json=spec.get("aliases", []),
            counterfactual_group_key=spec.get("counterfactual_group_key"),
            metadata_json={
                **source.metadata,
                "sample_pack_id": SAMPLE_PACK_ID,
                "synthetic": True,
            },
            label=label,
        )
        documents.append(document)

    try:
        session.add_all(documents)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    imported_documents = list(
        (
            await session.scalars(
                select(SourceDocument)
                .where(SourceDocument.dataset_id == dataset.id)
                .options(selectinload(SourceDocument.label))
                .order_by(SourceDocument.position)
            )
        ).all()
    )
    return pack.summary, dataset.id, imported_documents
