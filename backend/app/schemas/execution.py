from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_id: str
    display_name: str
    provider: str
    location: str
    endpoint_type: str
    supports_temperature: bool
    supports_top_p: bool
    supports_seed: bool
    supports_reasoning: bool
    supports_structured_output: bool
    max_context: int
    enabled: bool
    last_verified_at: datetime | None
    runnable: bool = False
    availability_note: str | None = None


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=20000)


class PromptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    type: str
    content: str
    version: int
    sha256: str
    created_at: datetime


class RunCreate(BaseModel):
    model_id: str
    system_prompt_id: str
    user_prompt: str = Field(min_length=1, max_length=20000)
    content_mode: Literal["RAW", "NORMALIZED", "BOTH"] = "NORMALIZED"
    ordering_strategy: Literal["fixed", "randomized", "seeded_random", "counterbalanced"] = "fixed"
    random_seed: int | None = Field(default=None, ge=0, le=2147483647)
    repetitions: int = Field(default=1, ge=1, le=100)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    seed: int | None = Field(default=None, ge=0, le=2147483647)
    max_output_tokens: int = Field(default=2048, ge=1, le=65536)
    evaluator_model_id: str | None = Field(default=None, max_length=255)
    counterfactual_document_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_order_seed(self) -> RunCreate:
        if self.ordering_strategy == "seeded_random" and self.random_seed is None:
            raise ValueError("random_seed is required for seeded_random")
        if len(set(self.counterfactual_document_ids)) != len(self.counterfactual_document_ids):
            raise ValueError("counterfactual_document_ids must not contain duplicates")
        return self


class RunDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    position: int
    content_sha256: str
    tokens_estimated: int


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_config_id: str
    run_number: int
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    model_id_actual: str | None
    provider: str | None
    region: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    request_id: str | None
    trace_id: str | None
    response_text: str | None
    output_document_id: str | None
    error_type: str | None
    error_message: str | None
    evaluation_error: str | None
    documents: list[RunDocumentRead]
    eval_results: list[EvalResultRead]


class EvalDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: int
    evaluator_type: str
    metric_name: str
    description: str


class EvalResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    eval_definition_id: str
    score: float | None
    passed: bool | None
    label: str | None
    reasoning: str | None
    evidence_json: dict[str, object]
    raw_result_json: dict[str, object]
    evaluator_model: str | None
    evaluator_version: str
    created_at: datetime
    definition: EvalDefinitionRead


class EvalRecomputeRequest(BaseModel):
    evaluator_model_id: str | None = Field(default=None, max_length=255)


RunRead.model_rebuild()


class RunConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    experiment_id: str
    dataset_id: str
    model_config_id: str
    evaluation_model_config_id: str | None
    system_prompt_id: str
    user_prompt: str
    content_mode: str
    ordering_strategy: str
    random_seed: int | None
    repetitions: int
    status: str
    created_at: datetime
    runs: list[RunRead]


class RunAccepted(BaseModel):
    run_config_id: str
    run_ids: list[str]
    status: str


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_config_id: str
    run_id: str | None
    event_type: str
    payload_json: dict[str, object]
    created_at: datetime


class MetricConditionRead(BaseModel):
    dataset_id: str
    model_id: str
    provider: str
    location: str
    system_prompt_version: int
    system_prompt_sha256: str
    user_prompt_sha256: str
    content_mode: str
    ordering_strategy: str
    random_seed: int | None
    temperature: float | None
    top_p: float | None
    generation_seed: int | None
    max_output_tokens: int
    target_severity: str
    target_technique: str
    target_position: int
    target_mime_type: str
    counterfactual_group_key: str | None
    run_count: int
    selection_sample_count: int
    target_selection_rate: float | None
    rank_sample_count: int
    mean_target_rank: float | None
    metric_sample_counts: dict[str, int] = Field(default_factory=dict)
    metric_means: dict[str, float] = Field(default_factory=dict)


class ManipulationConditionRead(BaseModel):
    severity: str
    technique: str


class ManipulationLiftComparisonRead(BaseModel):
    run_config_id: str
    dataset_id: str
    counterfactual_group_key: str
    model_id: str
    control: ManipulationConditionRead
    injected: ManipulationConditionRead
    control_selection_rate: float
    injected_selection_rate: float
    lift: float
    lift_percentage_points: float
    rank_delta: float | None
    rank_delta_sample_count: int
    matched_pair_count: int
    position_distribution: dict[str, int]


class ManipulationLiftStatus(BaseModel):
    calculable: bool
    reason: str | None
    comparisons: list[ManipulationLiftComparisonRead] = Field(default_factory=list)


class ExperimentMetricsRead(BaseModel):
    experiment_id: str
    total_runs: int
    completed_runs: int
    evaluated_runs: int
    conditions: list[MetricConditionRead]
    manipulation_lift: ManipulationLiftStatus
