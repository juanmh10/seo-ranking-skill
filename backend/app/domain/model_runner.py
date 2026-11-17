from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ModelRequest:
    model_id: str
    project: str
    location: str
    system_prompt: str
    user_prompt: str
    source_texts: tuple[str, ...]
    temperature: float | None
    top_p: float | None
    seed: int | None
    max_output_tokens: int
    response_json_schema: dict[str, object] | None = None
    endpoint_type: str = "vertex_gemini"


@dataclass(frozen=True)
class ModelResponse:
    text: str
    model_id_actual: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    request_id: str | None
    trace_id: str | None


@dataclass(frozen=True)
class ModelStreamEvent:
    text_delta: str = ""
    response: ModelResponse | None = None


class ModelRunner(Protocol):
    async def run(self, request: ModelRequest) -> ModelResponse: ...

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]: ...
