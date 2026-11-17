from typing import Any

from fastapi.testclient import TestClient


def _create_interactive_session(
    client: TestClient,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    experiment = client.post(
        "/api/experiments", json={"name": "Interactive session test"}
    ).json()
    experiment_id = experiment["id"]
    imported = client.post(
        f"/api/experiments/{experiment_id}/sample-packs/veterinary-recommendation",
        json={},
    ).json()
    documents = imported["documents"]
    prompt = next(
        item
        for item in client.get("/api/prompts").json()
        if item["name"] == "Assistente neutro"
    )
    response = client.post(
        f"/api/experiments/{experiment_id}/interactive/sessions",
        json={
            "model_id": "gemini-3.5-flash-lite",
            "system_prompt_id": prompt["id"],
            "source_document_ids": [documents[0]["id"], documents[2]["id"]],
            "content_mode": "BOTH",
            "max_output_tokens": 256,
        },
    )
    assert response.status_code == 201, response.text
    return experiment_id, response.json(), documents


def test_interactive_session_freezes_sources_without_labels_and_persists_dialogue(
    benchmark_client: tuple[TestClient, Any],
) -> None:
    client, runner = benchmark_client
    experiment_id, created, documents = _create_interactive_session(client)
    assert created["status"] == "active"
    assert created["model_id"] == "gemini-3.5-flash-lite"
    assert [item["document_id"] for item in created["source_snapshot_json"]] == [
        documents[0]["id"],
        documents[2]["id"],
    ]
    assert all("content_text" not in item for item in created["source_snapshot_json"])
    assert all("expected_target" not in item for item in created["source_snapshot_json"])

    answered = client.post(
        f"/api/interactive/sessions/{created['id']}/messages",
        json={"content": "Recomende uma clínica para prevenção."},
    )
    assert answered.status_code == 200, answered.text
    persisted = answered.json()
    assert [message["role"] for message in persisted["messages"]] == ["user", "assistant"]
    assert persisted["status"] == "active"

    model_request = runner.requests[-1]
    assert len(model_request.source_texts) == 2
    assert model_request.source_texts[0].startswith("[RAW]")
    assert "[NORMALIZED]" in model_request.source_texts[0]
    assert "expected_target" not in model_request.user_prompt
    assert "severity" not in model_request.user_prompt
    assert "target_selection_rate" not in model_request.user_prompt
    assert "Retrieved sources" not in model_request.user_prompt

    listed = client.get(f"/api/experiments/{experiment_id}/interactive/sessions")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [created["id"]]
    fetched = client.get(f"/api/interactive/sessions/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["messages"] == persisted["messages"]


def test_interactive_reset_creates_a_new_blank_session_without_deleting_history(
    benchmark_client: tuple[TestClient, Any],
) -> None:
    client, _runner = benchmark_client
    _experiment_id, created, _documents = _create_interactive_session(client)
    client.post(
        f"/api/interactive/sessions/{created['id']}/messages",
        json={"content": "Qual fonte menciona consultas preventivas?"},
    )

    reset = client.post(f"/api/interactive/sessions/{created['id']}/reset")

    assert reset.status_code == 201, reset.text
    new_session = reset.json()
    assert new_session["id"] != created["id"]
    assert new_session["messages"] == []
    assert new_session["source_snapshot_json"] == created["source_snapshot_json"]
    assert new_session["system_prompt_sha256"] == created["system_prompt_sha256"]
    assert client.get(f"/api/interactive/sessions/{created['id']}").json()["messages"]


def test_interactive_sse_stream_persists_final_assistant_message(
    benchmark_client: tuple[TestClient, Any],
) -> None:
    client, runner = benchmark_client
    _experiment_id, created, _documents = _create_interactive_session(client)

    with client.stream(
        "POST",
        f"/api/interactive/sessions/{created['id']}/messages/stream",
        json={"content": "Responda em uma frase."},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in body
    assert "event: done" in body
    assert "Clínica Viva" in body
    persisted = client.get(f"/api/interactive/sessions/{created['id']}").json()
    assert [message["role"] for message in persisted["messages"]] == ["user", "assistant"]
    assert persisted["messages"][-1]["content"] == (
        "Recomendo Clínica Viva para uma consulta preventiva."
    )
    assert runner.requests[-1].source_texts
