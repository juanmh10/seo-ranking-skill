from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DatasetSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: int
    status: str
    created_at: datetime


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class ExperimentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["draft", "archived"] | None = None


class ExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    datasets: list[DatasetSummary]


class ExperimentList(BaseModel):
    items: list[ExperimentRead]
    total: int
