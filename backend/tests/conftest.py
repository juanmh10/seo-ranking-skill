import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import ConfiguredModel, Settings
from app.domain.model_runner import ModelRequest, ModelResponse, ModelStreamEvent
from app.main import create_app


class DeterministicModelRunner:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def run(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.system_prompt.startswith("You are a read-only research analysis assistant"):
            response_text = "The persisted runs show a synthetic evaluation result."
        elif request.response_json_schema is not None:
            judgment = {
                "score": 0.25,
                "label": "low",
                "reasoning": "Synthetic test judgment.",
                "evidence": ["Synthetic evidence."],
            }
            response_text = json.dumps(
                {
                    "injection_compliance": judgment,
                    "claim_adoption": judgment,
                    "citation_adoption": judgment,
                    "competitor_suppression": judgment,
                    "fabricated_authority_adoption": judgment,
                    "source_grounding": judgment,
                    "unsupported_claim_rate": judgment,
                    "injection_awareness": judgment,
                }
            )
        elif any(
            "rank-delta-neutral-control-sentinel" in source for source in request.source_texts
        ):
            response_text = (
                "Recomendo Hospital Pata Serena para a consulta preventiva. "
                "Clínica Viva também é uma opção."
            )
        else:
            response_text = "Recomendo Clínica Viva para uma consulta preventiva."
        return ModelResponse(
            text=response_text,
            model_id_actual=request.model_id,
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            request_id=f"fake-{len(self.requests)}",
            trace_id=f"trace-{len(self.requests)}",
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        response = await self.run(request)
        midpoint = max(1, len(response.text) // 2)
        yield ModelStreamEvent(text_delta=response.text[:midpoint])
        yield ModelStreamEvent(text_delta=response.text[midpoint:])
        yield ModelStreamEvent(response=response)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "test.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{database_path}",
        auto_create_schema=True,
        gcp_project=None,
        xai_api_key=None,
        model_registry=[],
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def benchmark_client(tmp_path: Path) -> Iterator[tuple[TestClient, DeterministicModelRunner]]:
    database_path = tmp_path / "benchmark.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{database_path}",
        auto_create_schema=True,
        gcp_project="synthetic-test-project",
        model_registry=[
            ConfiguredModel(
                model_id="gemini-3.5-flash-lite",
                display_name="Gemini 3.5 Flash-Lite (fake)",
                location="global",
                supports_structured_output=True,
                max_context=1_048_576,
                enabled=True,
            ),
            ConfiguredModel(
                model_id="claude-sonnet-5",
                display_name="Claude Sonnet 5",
                provider="anthropic",
                endpoint_type="vertex_anthropic",
                location="global",
                max_context=1_000_000,
                enabled=True,
            ),
            ConfiguredModel(
                model_id="grok-4.7",
                display_name="Grok 4.7",
                provider="xai",
                endpoint_type="xai_responses",
                location="us-east-1",
                max_context=500_000,
                enabled=True,
            ),
        ],
    )
    runner = DeterministicModelRunner()
    with TestClient(create_app(settings, model_runner=runner)) as test_client:
        yield test_client, runner
