from fastapi.testclient import TestClient


def test_experiment_lifecycle(client: TestClient) -> None:
    created = client.post(
        "/api/experiments",
        json={"name": "Veterinary recommendations", "description": "Initial study"},
    )

    assert created.status_code == 201
    experiment = created.json()
    assert experiment["status"] == "draft"
    assert experiment["datasets"][0]["version"] == 1
    assert experiment["datasets"][0]["status"] == "draft"

    listed = client.get("/api/experiments")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    updated = client.patch(
        f"/api/experiments/{experiment['id']}",
        json={"name": "Veterinary recommendations v2"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Veterinary recommendations v2"

    archived = client.patch(
        f"/api/experiments/{experiment['id']}",
        json={"status": "archived"},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.get("/api/experiments").json()["total"] == 0
    assert client.get("/api/experiments?include_archived=true").json()["total"] == 1


def test_missing_experiment_returns_404(client: TestClient) -> None:
    response = client.get("/api/experiments/missing")

    assert response.status_code == 404
