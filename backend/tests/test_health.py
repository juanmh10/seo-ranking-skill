from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_checks_database(client: TestClient) -> None:
    response = client.get("/api/readiness")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"
