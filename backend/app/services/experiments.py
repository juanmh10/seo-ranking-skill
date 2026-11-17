from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.experiment import Dataset, Experiment, ExperimentStatus
from app.schemas.experiment import ExperimentCreate, ExperimentUpdate


class ExperimentNotFoundError(Exception):
    pass


class ExperimentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: ExperimentCreate) -> Experiment:
        experiment = Experiment(name=payload.name.strip(), description=payload.description)
        experiment.datasets.append(
            Dataset(name=f"{payload.name.strip()} — dataset", version=1, status="draft")
        )
        self.session.add(experiment)
        await self.session.commit()
        return await self.get(experiment.id)

    async def list(self, *, include_archived: bool = False) -> tuple[list[Experiment], int]:
        filters = []
        if not include_archived:
            filters.append(Experiment.status != ExperimentStatus.ARCHIVED.value)

        statement = (
            select(Experiment)
            .where(*filters)
            .options(selectinload(Experiment.datasets))
            .order_by(Experiment.updated_at.desc())
        )
        count_statement = select(func.count(Experiment.id)).where(*filters)
        items = list((await self.session.scalars(statement)).unique().all())
        total = int(await self.session.scalar(count_statement) or 0)
        return items, total

    async def get(self, experiment_id: str) -> Experiment:
        statement = (
            select(Experiment)
            .where(Experiment.id == experiment_id)
            .options(selectinload(Experiment.datasets))
        )
        experiment = (await self.session.scalars(statement)).first()
        if experiment is None:
            raise ExperimentNotFoundError(experiment_id)
        return experiment

    async def update(self, experiment_id: str, payload: ExperimentUpdate) -> Experiment:
        experiment = await self.get(experiment_id)
        changes = payload.model_dump(exclude_unset=True)
        if "name" in changes:
            changes["name"] = changes["name"].strip()
        for field, value in changes.items():
            setattr(experiment, field, value)
        await self.session.commit()
        return await self.get(experiment_id)
