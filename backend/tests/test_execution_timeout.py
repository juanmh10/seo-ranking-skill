import asyncio
import time
from typing import Any

from fastapi.testclient import TestClient

from app.domain.model_runner import ModelRequest, ModelStreamEvent


def test_model_timeout_persists_sanitized_failure(
    benchmark_client: tuple[TestClient, Any], monkeypatch: Any
) -> None:
    client, runner = benchmark_client
    client.app.state.settings.model_timeout_seconds = 1

    async def partial_then_never(_request: ModelRequest):
        yield ModelStreamEvent(text_delta="Partial benchmark response.")
        await asyncio.Event().wait()
        raise AssertionError("The timed out stream should not return")

    monkeypatch.setattr(runner, "stream", partial_then_never)

    experiment_response = client.post(
        "/api/experiments",
        json={"name": "Timeout handling"},
    )
    assert experiment_response.status_code == 201
    experiment_id = experiment_response.json()["id"]

    imported_response = client.post(
        f"/api/experiments/{experiment_id}/sample-packs/veterinary-recommendation",
        json={},
    )
    assert imported_response.status_code == 201
    prompt = next(
        item
        for item in client.get("/api/prompts").json()
        if item["name"] == "Assistente neutro"
    )

    accepted_response = client.post(
        f"/api/experiments/{experiment_id}/runs",
        headers={"Idempotency-Key": "timeout-test-1"},
        json={
            "model_id": "gemini-3.5-flash-lite",
            "system_prompt_id": prompt["id"],
            "user_prompt": "Resuma as fontes.",
            "repetitions": 1,
        },
    )
    assert accepted_response.status_code == 202
    accepted = accepted_response.json()

    run_config = None
    for _ in range(100):
        run_config_response = client.get(f"/api/run-configs/{accepted['run_config_id']}")
        assert run_config_response.status_code == 200
        run_config = run_config_response.json()
        if run_config["status"] in {"completed", "failed", "interrupted"}:
            break
        time.sleep(0.02)

    assert run_config is not None
    assert run_config["status"] == "failed"
    run = run_config["runs"][0]
    assert run["status"] == "failed"
    assert run["error_type"] == "TimeoutError"
    assert run["error_message"] == "Model execution timed out after the configured backend limit"
    assert run["response_text"] == "Partial benchmark response."
    events = client.get(f"/api/runs/{run['id']}/events").json()
    assert any(
        event["event_type"] == "run_output_delta"
        and event["payload_json"]["text_delta"] == "Partial benchmark response."
        for event in events
    )
    assert any(event["event_type"] == "run_failed" for event in events)
