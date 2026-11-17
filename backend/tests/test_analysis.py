import time
from typing import Any

from fastapi.testclient import TestClient


def test_analysis_session_reads_persisted_runs_and_persists_conversation(
    benchmark_client: tuple[TestClient, Any],
) -> None:
    client, runner = benchmark_client
    experiment_response = client.post(
        "/api/experiments",
        json={"name": "Analysis session integration"},
    )
    assert experiment_response.status_code == 201
    experiment_id = experiment_response.json()["id"]

    imported = client.post(
        f"/api/experiments/{experiment_id}/sample-packs/veterinary-recommendation",
        json={},
    )
    assert imported.status_code == 201
    prompt = next(
        item
        for item in client.get("/api/prompts").json()
        if item["name"] == "Assistente neutro"
    )
    accepted = client.post(
        f"/api/experiments/{experiment_id}/runs",
        headers={"Idempotency-Key": "analysis-session-run"},
        json={
            "model_id": "gemini-3.5-flash-lite",
            "system_prompt_id": prompt["id"],
            "user_prompt": imported.json()["sample_pack"]["recommended_question"],
            "repetitions": 1,
        },
    )
    assert accepted.status_code == 202
    run_config_id = accepted.json()["run_config_id"]
    run_config = None
    for _ in range(100):
        run_config = client.get(f"/api/run-configs/{run_config_id}").json()
        if run_config["status"] in {"completed", "failed", "interrupted"}:
            break
        time.sleep(0.02)
    assert run_config is not None and run_config["status"] == "completed"
    run_id = run_config["runs"][0]["id"]

    created = client.post(
        f"/api/experiments/{experiment_id}/analysis/sessions",
        json={"run_ids": [run_id]},
    )
    assert created.status_code == 201, created.text
    analysis_session = created.json()
    assert analysis_session["analysis_model_id"] == "gemini-3.5-flash-lite"
    assert analysis_session["selected_run_ids_json"] == [run_id]
    assert analysis_session["messages"] == []

    answered = client.post(
        f"/api/analysis/sessions/{analysis_session['id']}/messages",
        json={"content": "Resuma os resultados persistidos desta execução."},
    )
    assert answered.status_code == 200, answered.text
    persisted = answered.json()
    assert persisted["status"] == "active"
    assert [message["role"] for message in persisted["messages"]] == ["user", "assistant"]
    assert "synthetic evaluation result" in persisted["messages"][1]["content"]

    analysis_request = runner.requests[-1]
    assert run_id in analysis_request.source_texts[0]
    assert "target_selection_rate" in analysis_request.source_texts[0]
    assert "expected_target" not in runner.requests[0].source_texts[0]

    fetched = client.get(f"/api/analysis/sessions/{analysis_session['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["messages"] == persisted["messages"]

    with client.stream(
        "POST",
        f"/api/analysis/sessions/{analysis_session['id']}/messages/stream",
        json={"content": "Quais limitações devo considerar?"},
    ) as stream_response:
        body = "".join(stream_response.iter_text())
    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in body
    assert "event: done" in body

    streamed = client.get(f"/api/analysis/sessions/{analysis_session['id']}").json()
    assert [message["role"] for message in streamed["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert streamed["status"] == "active"
