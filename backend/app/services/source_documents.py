from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.execution import RunDocument
from app.models.experiment import Dataset, DatasetStatus, Experiment
from app.models.source_document import DocumentLabel, SourceDocument, SourceOrigin
from app.schemas.source_document import (
    DocumentLabelUpdate,
    SourceDocumentUpdate,
)
from app.services.source_normalizer import NormalizedSource


class SourceDocumentNotFoundError(Exception):
    pass


class SourceDocumentConflictError(Exception):
    pass


class DatasetNotEditableError(Exception):
    pass


@dataclass(frozen=True)
class SourceProvenance:
    origin: SourceOrigin
    iteration: int = 0
    parent_document_id: str | None = None
    metadata: dict[str, object] | None = None


class SourceDocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def current_dataset(self, experiment_id: str) -> Dataset:
        statement = (
            select(Dataset)
            .join(Experiment)
            .where(Experiment.id == experiment_id)
            .order_by(Dataset.version.desc())
            .limit(1)
        )
        dataset = (await self.session.scalars(statement)).first()
        if dataset is None:
            raise SourceDocumentNotFoundError("Experiment not found")
        return dataset

    async def create(
        self,
        *,
        experiment_id: str,
        source: NormalizedSource,
        provenance: SourceProvenance,
        position: int | None = None,
        entity_key: str | None = None,
        entity_name: str | None = None,
        aliases: list[str] | None = None,
        counterfactual_group_key: str | None = None,
        auto_assign: bool = True,
    ) -> SourceDocument:
        dataset = await self.current_dataset(experiment_id)
        if dataset.status == DatasetStatus.FROZEN.value:
            dataset = await self._fork_dataset(dataset)
        resolved_parent_id = await self._resolve_parent(dataset.id, provenance.parent_document_id)
        selected_position = position
        if selected_position is None and auto_assign:
            selected_position = await self._next_free_position(dataset.id)
        await self._ensure_position_available(dataset.id, selected_position)

        document_id = str(uuid.uuid4())
        entity_name = (entity_name or str(source.metadata.get("title") or "")).strip()
        if not entity_name:
            entity_name = (
                source.filename.rsplit(".", maxsplit=1)[0].replace("_", " ").replace("-", " ")
            )
        entity_key = entity_key.strip() or None if entity_key else None
        counterfactual_group_key = (
            counterfactual_group_key.strip() or None if counterfactual_group_key else None
        )
        aliases = list(dict.fromkeys(alias.strip() for alias in (aliases or []) if alias.strip()))
        document = SourceDocument(
            id=document_id,
            dataset_id=dataset.id,
            lineage_id=document_id,
            parent_document_id=resolved_parent_id,
            filename=source.filename,
            mime_type=source.mime_type,
            content_type=source.content_type,
            source_representation=source.representation.value,
            origin=provenance.origin.value,
            sha256=source.sha256,
            byte_size=source.byte_size,
            raw_content=source.raw_content,
            normalized_content=source.normalized_content,
            position=selected_position,
            iteration=provenance.iteration,
            entity_key=entity_key,
            entity_name=entity_name,
            aliases_json=aliases,
            counterfactual_group_key=counterfactual_group_key,
            metadata_json={**source.metadata, **(provenance.metadata or {})},
            label=DocumentLabel(severity="neutral", technique="none"),
        )
        self.session.add(document)
        await self.session.commit()
        return await self.get(document.id)

    async def list(self, experiment_id: str) -> tuple[list[SourceDocument], int]:
        dataset = await self.current_dataset(experiment_id)
        statement = (
            select(SourceDocument)
            .where(SourceDocument.dataset_id == dataset.id)
            .options(selectinload(SourceDocument.label))
            .order_by(
                SourceDocument.position.is_(None),
                SourceDocument.position,
                SourceDocument.iteration.desc(),
                SourceDocument.created_at.desc(),
            )
        )
        documents = list((await self.session.scalars(statement)).all())
        active_count = sum(document.position is not None for document in documents)
        return documents, active_count

    async def get(self, document_id: str) -> SourceDocument:
        statement = (
            select(SourceDocument)
            .where(SourceDocument.id == document_id)
            .options(selectinload(SourceDocument.label))
        )
        document = (await self.session.scalars(statement)).first()
        if document is None:
            raise SourceDocumentNotFoundError(document_id)
        return document

    async def update(self, document_id: str, payload: SourceDocumentUpdate) -> SourceDocument:
        document = await self._editable_document(document_id)
        dataset = await self.session.get(Dataset, document.dataset_id)
        if dataset is None:
            raise SourceDocumentNotFoundError(document_id)
        if dataset.status != DatasetStatus.DRAFT.value:
            raise DatasetNotEditableError("Could not create a writable dataset version")
        changes = payload.model_dump(exclude_unset=True)
        if "position" in changes:
            await self._ensure_position_available(
                document.dataset_id,
                changes["position"],
                exclude_document_id=document.id,
            )
        if "aliases" in changes:
            changes["aliases_json"] = [
                alias.strip() for alias in changes.pop("aliases") if alias.strip()
            ]
        for field, value in changes.items():
            setattr(document, field, value.strip() if isinstance(value, str) else value)
        await self.session.commit()
        return await self.get(document.id)

    async def update_label(self, document_id: str, payload: DocumentLabelUpdate) -> SourceDocument:
        document = await self._editable_document(document_id)
        dataset = await self.session.get(Dataset, document.dataset_id)
        if dataset is None:
            raise SourceDocumentNotFoundError(document_id)
        if dataset.status != DatasetStatus.DRAFT.value:
            raise DatasetNotEditableError("Could not create a writable dataset version")
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("expected_target"):
            dataset_documents = select(SourceDocument.id).where(
                SourceDocument.dataset_id == document.dataset_id
            )
            reset_labels = update(DocumentLabel).where(
                DocumentLabel.document_id.in_(dataset_documents)
            )
            if document.counterfactual_group_key:
                reset_document_ids = select(SourceDocument.id).where(
                    SourceDocument.dataset_id == document.dataset_id,
                    SourceDocument.counterfactual_group_key
                    != document.counterfactual_group_key,
                )
                ungrouped_document_ids = select(SourceDocument.id).where(
                    SourceDocument.dataset_id == document.dataset_id,
                    SourceDocument.counterfactual_group_key.is_(None),
                )
                reset_labels = reset_labels.where(
                    DocumentLabel.document_id.in_(reset_document_ids.union(ungrouped_document_ids))
                )
            await self.session.execute(reset_labels.values(expected_target=False))
        for field, value in changes.items():
            setattr(document.label, field, value)
        await self.session.commit()
        return await self.get(document.id)

    async def delete(self, document_id: str) -> None:
        document = await self._editable_document(document_id)
        referenced = await self.session.scalar(
            select(RunDocument.id).where(RunDocument.document_id == document.id).limit(1)
        )
        if referenced is not None:
            raise SourceDocumentConflictError("Source belongs to a persisted run snapshot")
        dataset = await self.session.get(Dataset, document.dataset_id)
        if dataset is None:
            raise SourceDocumentNotFoundError(document_id)
        if dataset.status != DatasetStatus.DRAFT.value:
            raise DatasetNotEditableError("Could not create a writable dataset version")
        await self.session.delete(document)
        await self.session.commit()

    async def _editable_document(self, document_id: str) -> SourceDocument:
        original = await self.get(document_id)
        source_dataset = await self.session.get(Dataset, original.dataset_id)
        if source_dataset is None:
            raise SourceDocumentNotFoundError(document_id)
        current = await self.current_dataset(source_dataset.experiment_id)
        if current.status == DatasetStatus.FROZEN.value:
            current = await self._fork_dataset(current)
        lineage_id = original.lineage_id or original.id
        current_document = await self.session.scalar(
            select(SourceDocument)
            .where(
                SourceDocument.dataset_id == current.id,
                SourceDocument.lineage_id == lineage_id,
            )
            .options(selectinload(SourceDocument.label))
        )
        if current_document is None:
            raise SourceDocumentNotFoundError(document_id)
        return current_document

    async def _fork_dataset(self, dataset: Dataset) -> Dataset:
        if dataset.status != DatasetStatus.FROZEN.value:
            return dataset
        documents = list(
            (
                await self.session.scalars(
                    select(SourceDocument)
                    .where(SourceDocument.dataset_id == dataset.id)
                    .options(selectinload(SourceDocument.label))
                    .order_by(SourceDocument.created_at, SourceDocument.id)
                )
            ).all()
        )
        new_dataset = Dataset(
            experiment_id=dataset.experiment_id,
            name=dataset.name,
            description=dataset.description,
            version=dataset.version + 1,
            status=DatasetStatus.DRAFT.value,
        )
        self.session.add(new_dataset)
        await self.session.flush()
        clones: dict[str, SourceDocument] = {}
        for old in documents:
            clone_id = str(uuid.uuid4())
            clone = SourceDocument(
                id=clone_id,
                lineage_id=old.lineage_id or old.id,
                dataset_id=new_dataset.id,
                filename=old.filename,
                mime_type=old.mime_type,
                content_type=old.content_type,
                source_representation=old.source_representation,
                origin=old.origin,
                sha256=old.sha256,
                byte_size=old.byte_size,
                raw_content=old.raw_content,
                normalized_content=old.normalized_content,
                position=old.position,
                iteration=old.iteration,
                entity_key=old.entity_key,
                entity_name=old.entity_name,
                aliases_json=list(old.aliases_json),
                counterfactual_group_key=old.counterfactual_group_key,
                metadata_json=dict(old.metadata_json),
                label=DocumentLabel(
                    severity=old.label.severity,
                    technique=old.label.technique,
                    expected_target=old.label.expected_target,
                    annotation=old.label.annotation,
                    annotator=old.label.annotator,
                )
                if old.label
                else None,
            )
            clones[old.id] = clone
            self.session.add(clone)
        await self.session.flush()
        for old in documents:
            if old.parent_document_id:
                clone = clones[old.id]
                parent_clone = clones.get(old.parent_document_id)
                if parent_clone is None:
                    raise SourceDocumentConflictError("Cannot copy a source with a missing parent")
                clone.parent_document_id = parent_clone.id
        await self.session.flush()
        return new_dataset

    async def _resolve_parent(self, dataset_id: str, parent_document_id: str | None) -> str | None:
        if parent_document_id is None:
            return None
        parent = await self.session.get(SourceDocument, parent_document_id)
        if parent is None:
            raise SourceDocumentConflictError("Parent source does not exist")
        if parent.dataset_id == dataset_id:
            return parent.id
        lineage_id = parent.lineage_id or parent.id
        current_parent = await self.session.scalar(
            select(SourceDocument.id).where(
                SourceDocument.dataset_id == dataset_id,
                SourceDocument.lineage_id == lineage_id,
            )
        )
        if current_parent is None:
            raise SourceDocumentConflictError("Parent source is not part of the current dataset")
        return current_parent

    async def _next_free_position(self, dataset_id: str) -> int | None:
        positions = set(
            await self.session.scalars(
                select(SourceDocument.position).where(
                    SourceDocument.dataset_id == dataset_id,
                    SourceDocument.position.is_not(None),
                )
            )
        )
        return next((position for position in range(1, 6) if position not in positions), None)

    async def _ensure_position_available(
        self,
        dataset_id: str,
        position: int | None,
        *,
        exclude_document_id: str | None = None,
    ) -> None:
        if position is None:
            return
        statement = select(func.count(SourceDocument.id)).where(
            SourceDocument.dataset_id == dataset_id,
            SourceDocument.position == position,
        )
        if exclude_document_id:
            statement = statement.where(SourceDocument.id != exclude_document_id)
        if int(await self.session.scalar(statement) or 0):
            raise SourceDocumentConflictError(f"Source slot {position} is already occupied")
