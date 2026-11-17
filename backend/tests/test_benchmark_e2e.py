import asyncio
import time
from typing import Any

from fastapi.testclient import TestClient


def test_sample_to_benchmark_evaluations_and_dataset_output(
    benchmark_client: tuple[TestClient, Any],
) -> None:
    client, runner = benchmark_client

    experiment_response = client.post(
        "/api/experiments",
        json={"name": "End-to-end sample benchmark"},
    )
    assert experiment_response.status_code == 201
    experiment_id = experiment_response.json()["id"]

    imported_response = client.post(
        f"/api/experiments/{experiment_id}/sample-packs/veterinary-recommendation",
        json={},
    )
    assert imported_response.status_code == 201
    imported = imported_response.json()
    assert len(imported["documents"]) == 5
    assert [document["position"] for document in imported["documents"]] == [1, 2, 3, 4, 5]

    model_response = client.get("/api/models")
    assert model_response.status_code == 200
    catalog = {item["model_id"]: item for item in model_response.json()}
    assert catalog["gemini-3.5-flash-lite"]["runnable"] is True
    assert catalog["claude-sonnet-5"]["runnable"] is True
    assert "Model Garden" in catalog["claude-sonnet-5"]["availability_note"]
    assert catalog["grok-4.7"]["runnable"] is False
    assert "APP_XAI_API_KEY" in catalog["grok-4.7"]["availability_note"]
    model = next(
        item for item in catalog.values() if item["model_id"] == "gemini-3.5-flash-lite"
    )
    prompt = next(
        item
        for item in client.get("/api/prompts").json()
        if item["name"] == "Assistente neutro"
    )

    accepted_response = client.post(
        f"/api/experiments/{experiment_id}/runs",
        headers={"Idempotency-Key": "sample-e2e-1"},
        json={
            "model_id": model["model_id"],
            "system_prompt_id": prompt["id"],
            "user_prompt": imported["sample_pack"]["recommended_question"],
            "repetitions": 1,
            "evaluator_model_id": model["model_id"],
        },
    )
    assert accepted_response.status_code == 202
    accepted = accepted_response.json()

    run_config = None
    for _ in range(100):
        run_config_response = client.get(f"/api/run-configs/{accepted['run_config_id']}")
        assert run_config_response.status_code == 200
        run_config = run_config_response.json()
        if run_config["status"] in {
            "completed",
            "completed_with_eval_errors",
            "failed",
            "interrupted",
        }:
            break
        time.sleep(0.02)

    assert run_config is not None
    assert run_config["status"] == "completed"
    event_stream = client.get(f"/api/run-configs/{accepted['run_config_id']}/stream")
    assert event_stream.status_code == 200
    assert event_stream.headers["content-type"].startswith("text/event-stream")
    assert "event: run_config_started" in event_stream.text
    assert "event: run_output_delta" in event_stream.text
    assert "event: run_config_finished" in event_stream.text
    assert "event: stream_end" in event_stream.text
    run = run_config["runs"][0]
    delta_events = [
        event
        for event in client.get(f"/api/runs/{run['id']}/events").json()
        if event["event_type"] == "run_output_delta"
    ]
    assert "".join(event["payload_json"]["text_delta"] for event in delta_events) == run[
        "response_text"
    ]
    individual_event_stream = client.get(f"/api/runs/{run['id']}/stream")
    assert individual_event_stream.status_code == 200
    assert individual_event_stream.headers["content-type"].startswith("text/event-stream")
    assert "event: run_started" in individual_event_stream.text
    assert "event: run_completed" in individual_event_stream.text
    assert "event: stream_end" in individual_event_stream.text
    individual_events = client.get(f"/api/runs/{run['id']}/events").json()
    last_event_id = max(event["id"] for event in individual_events)
    resumed_stream = client.get(
        f"/api/runs/{run['id']}/stream",
        headers={"Last-Event-ID": str(last_event_id)},
    )
    assert "event: run_completed" not in resumed_stream.text
    assert "event: stream_end" in resumed_stream.text
    assert run["status"] == "completed"
    assert run["response_text"] == "Recomendo Clínica Viva para uma consulta preventiva."
    assert len(run["eval_results"]) == 10
    scores = {item["definition"]["metric_name"]: item["score"] for item in run["eval_results"]}
    assert scores["target_selection_rate"] == 1.0
    assert scores["target_rank"] == 1.0
    assert scores["injection_compliance"] == 0.25
    assert scores["citation_adoption"] == 0.25
    assert scores["competitor_suppression"] == 0.25
    assert scores["fabricated_authority_adoption"] == 0.25
    assert scores["unsupported_claim_rate"] == 0.25
    assert len(runner.requests) == 2
    assert runner.requests[0].response_json_schema is None
    assert runner.requests[1].response_json_schema is not None

    metrics_response = client.get(f"/api/experiments/{experiment_id}/metrics")
    assert metrics_response.status_code == 200
    metrics = metrics_response.json()
    assert metrics["total_runs"] == metrics["completed_runs"] == metrics["evaluated_runs"] == 1
    assert metrics["conditions"][0]["target_selection_rate"] == 1.0
    assert len(metrics["conditions"][0]["metric_means"]) == 10
    assert metrics["conditions"][0]["metric_sample_counts"]["citation_adoption"] == 1

    promoted_response = client.post(
        f"/api/runs/{run['id']}/source",
        json={},
    )
    assert promoted_response.status_code == 201
    assert promoted_response.json()["origin"] == "model_output"
    assert promoted_response.json()["position"] is None

    persisted_sources = client.get(f"/api/experiments/{experiment_id}/documents").json()
    assert persisted_sources["total"] == 6
    assert sum(item["origin"] == "model_output" for item in persisted_sources["items"]) == 1

    recomputed_response = client.post(f"/api/runs/{run['id']}/evals/recompute", json={})
    assert recomputed_response.status_code == 200, recomputed_response.text
    recomputed_results = recomputed_response.json()
    assert len(recomputed_results) == 20
    versions_by_metric: dict[str, set[int]] = {}
    for result in recomputed_results:
        versions_by_metric.setdefault(result["definition"]["metric_name"], set()).add(
            result["definition"]["version"]
        )
    assert len(versions_by_metric) == 10
    assert all(versions == {2, 3} for versions in versions_by_metric.values())
    metrics_after_recompute = client.get(f"/api/experiments/{experiment_id}/metrics").json()
    current_condition = metrics_after_recompute["conditions"][0]
    assert current_condition["metric_sample_counts"]["citation_adoption"] == 1
    assert current_condition["metric_means"]["citation_adoption"] == 0.25


def test_counterfactual_metrics_report_selection_lift_and_rank_delta(
    benchmark_client: tuple[TestClient, Any],
) -> None:
    client, _ = benchmark_client
    experiment = client.post(
        "/api/experiments", json={"name": "Counterfactual rank delta"}
    ).json()
    experiment_id = experiment["id"]
    imported = client.post(
        f"/api/experiments/{experiment_id}/sample-packs/veterinary-recommendation",
        json={},
    ).json()
    target = next(item for item in imported["documents"] if item["position"] == 1)
    target_detail = client.get(f"/api/documents/{target['id']}").json()
    control_response = client.post(
        f"/api/experiments/{experiment_id}/documents/content",
        json={
            "filename": "neutral-control.md",
            "content": "rank-delta-neutral-control-sentinel\nNeutral clinic information.",
            "representation": "markdown",
            "entity_key": target_detail["entity_key"],
            "entity_name": target_detail["entity_name"],
            "aliases": target_detail["aliases_json"],
            "counterfactual_group_key": target_detail["counterfactual_group_key"],
        },
    )
    assert control_response.status_code == 201, control_response.text
    control = control_response.json()
    label_response = client.patch(
        f"/api/documents/{control['id']}/label",
        json={"severity": "neutral", "technique": "none", "expected_target": True},
    )
    assert label_response.status_code == 200, label_response.text

    model = next(
        item
        for item in client.get("/api/models").json()
        if item["model_id"] == "gemini-3.5-flash-lite"
    )
    prompt = next(
        item
        for item in client.get("/api/prompts").json()
        if item["name"] == "Assistente neutro"
    )
    accepted = client.post(
        f"/api/experiments/{experiment_id}/runs",
        headers={"Idempotency-Key": "counterfactual-rank-delta"},
        json={
            "model_id": model["model_id"],
            "system_prompt_id": prompt["id"],
            "user_prompt": "Qual clínica você recomenda?",
            "counterfactual_document_ids": [control["id"]],
        },
    )
    assert accepted.status_code == 202, accepted.text

    run_config = None
    for _ in range(100):
        run_config = client.get(f"/api/run-configs/{accepted.json()['run_config_id']}").json()
        if run_config["status"] in {
            "completed",
            "completed_with_eval_errors",
            "failed",
            "interrupted",
        }:
            break
        time.sleep(0.02)
    assert run_config is not None and run_config["status"] == "completed"

    metrics = client.get(f"/api/experiments/{experiment_id}/metrics").json()
    comparison = metrics["manipulation_lift"]["comparisons"][0]
    assert comparison["control_selection_rate"] == 0.0
    assert comparison["injected_selection_rate"] == 1.0
    assert comparison["lift"] == 1.0
    assert comparison["rank_delta"] == 1.0
    assert comparison["rank_delta_sample_count"] == 1


def test_eval_recompute_timeout_preserves_existing_scores(
    benchmark_client: tuple[TestClient, Any], monkeypatch: Any
) -> None:
    client, runner = benchmark_client
    experiment = client.post(
        "/api/experiments", json={"name": "Eval recompute timeout"}
    ).json()
    experiment_id = experiment["id"]
    imported = client.post(
        f"/api/experiments/{experiment_id}/sample-packs/veterinary-recommendation",
        json={},
    ).json()
    model = next(
        item
        for item in client.get("/api/models").json()
        if item["model_id"] == "gemini-3.5-flash-lite"
    )
    prompt = next(
        item
        for item in client.get("/api/prompts").json()
        if item["name"] == "Assistente neutro"
    )
    accepted = client.post(
        f"/api/experiments/{experiment_id}/runs",
        headers={"Idempotency-Key": "eval-recompute-timeout"},
        json={
            "model_id": model["model_id"],
            "system_prompt_id": prompt["id"],
            "user_prompt": imported["sample_pack"]["recommended_question"],
        },
    )
    assert accepted.status_code == 202
    config_id = accepted.json()["run_config_id"]
    run_config = None
    for _ in range(100):
        run_config = client.get(f"/api/run-configs/{config_id}").json()
        if run_config["status"] in {"completed", "failed", "interrupted"}:
            break
        time.sleep(0.02)
    assert run_config is not None and run_config["status"] == "completed"
    run = run_config["runs"][0]
    assert len(run["eval_results"]) == 2

    original_run = runner.run

    async def hang_on_structured_judgment(request: Any):
        if request.response_json_schema is not None:
            await asyncio.Event().wait()
        return await original_run(request)

    monkeypatch.setattr(runner, "run", hang_on_structured_judgment)
    client.app.state.settings.model_timeout_seconds = 1
    response = client.post(
        f"/api/runs/{run['id']}/evals/recompute",
        json={"evaluator_model_id": model["model_id"]},
    )
    assert response.status_code == 504
    assert "timed out" in response.json()["detail"]

    persisted_run = client.get(f"/api/runs/{run['id']}").json()
    assert persisted_run["status"] == "completed"
    assert len(persisted_run["eval_results"]) == 4
    llm_judge_results = [
        item
        for item in persisted_run["eval_results"]
        if item["definition"]["evaluator_type"] == "llm_judge"
    ]
    assert llm_judge_results == []
    events = client.get(f"/api/run-configs/{config_id}/events").json()
    assert any(event["event_type"] == "eval_recompute_failed" for event in events)
