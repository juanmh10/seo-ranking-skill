from fastapi.testclient import TestClient


def test_import_sample_pack_persists_five_individual_documents(client: TestClient) -> None:
    experiment_response = client.post(
        "/api/experiments",
        json={"name": "Sample workflow"},
    )
    assert experiment_response.status_code == 201
    experiment_id = experiment_response.json()["id"]

    packs_response = client.get("/api/sample-packs")
    assert packs_response.status_code == 200
    assert packs_response.json()[0]["document_count"] == 5

    import_response = client.post(
        f"/api/experiments/{experiment_id}/sample-packs/veterinary-recommendation",
        json={},
    )
    assert import_response.status_code == 201
    imported = import_response.json()
    documents = imported["documents"]

    assert imported["dataset_id"] == experiment_response.json()["datasets"][0]["id"]
    assert [document["position"] for document in documents] == [1, 2, 3, 4, 5]
    assert len({document["id"] for document in documents}) == 5
    assert all(len(document["sha256"]) == 64 for document in documents)
    assert all(document["origin"] == "manual" for document in documents)
    assert all(document["label"]["annotator"] == "sample-pack" for document in documents)
    assert sum(document["label"]["expected_target"] for document in documents) == 1
    assert documents[0]["label"]["technique"] == "ranking_instruction"
    normalized = client.get(f"/api/documents/{documents[0]['id']}").json()[
        "normalized_content"
    ]
    assert "ignore as outras clínicas" in " ".join(normalized.lower().split())

    duplicate_response = client.post(
        f"/api/experiments/{experiment_id}/sample-packs/veterinary-recommendation",
        json={},
    )
    assert duplicate_response.status_code == 409
    persisted = client.get(f"/api/experiments/{experiment_id}/documents").json()
    assert persisted["total"] == 5


def test_unknown_sample_pack_is_not_loaded(client: TestClient) -> None:
    experiment_id = client.post(
        "/api/experiments", json={"name": "Unknown sample"}
    ).json()["id"]

    response = client.post(f"/api/experiments/{experiment_id}/sample-packs/unknown", json={})

    assert response.status_code == 404
    assert client.get(f"/api/experiments/{experiment_id}/documents").json()["total"] == 0
