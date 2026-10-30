DS = {"name": "S2B_MSIL2A_20230115_T43QCF", "source": "Copernicus Data Space", "mission": "Sentinel-2",
      "sensor": "MSI L2A", "acquisition_date": "2023-01-15", "region": "pune", "processing_baseline": "05.09"}


def test_datasets_empty(client):
    body = client.get("/api/datasets").json()
    assert body["count"] == 0 and body["items"] == [] and "No datasets" in body["note"]


def test_dataset_crud_and_filters(client, seeded):
    r = client.post("/api/datasets", json=DS)
    assert r.status_code == 201
    d = r.json()
    assert d["region"] == "pune" and d["status"] == "registered" and d["id"] > 0
    assert client.get(f"/api/datasets/{d['id']}").json()["name"] == DS["name"]
    assert client.get("/api/datasets?region=pune").json()["count"] == 1
    assert client.get("/api/datasets?region=surat").json()["count"] == 0
    assert client.get("/api/datasets?status=failed").json()["count"] == 0


def test_dataset_errors(client, seeded):
    assert client.post("/api/datasets", json={**DS, "region": "atlantis"}).status_code == 404
    assert client.post("/api/datasets", json={**DS, "status": "weird"}).status_code == 422
    assert client.post("/api/datasets", json={**DS, "acquisition_date": "not-a-date"}).status_code == 422
    assert client.get("/api/datasets/999").status_code == 404
    assert client.get("/api/datasets/abc").status_code == 422
    assert client.get("/api/datasets?limit=0").status_code == 422
    client.post("/api/datasets", json=DS)
    assert client.post("/api/datasets", json=DS).status_code == 409  # same name in same region


def test_jobs_empty_and_missing(client):
    assert client.get("/api/jobs").json() == {"items": [], "count": 0}
    assert client.get("/api/jobs/does-not-exist").status_code == 404
    assert client.get("/api/jobs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_job_create_and_fetch(client, seeded):
    r = client.post("/api/jobs", json={"region": "pune", "index_name": "ndvi"})
    assert r.status_code == 201
    j = r.json()
    assert j["status"] == "queued" and j["kind"] == "regional_analysis" and j["region"] == "pune"
    assert client.get(f"/api/jobs/{j['id']}").json()["id"] == j["id"]
    assert client.get("/api/jobs?status=queued").json()["count"] == 1
    assert client.get("/api/jobs?status=completed").json()["count"] == 0


def test_job_validation(client, seeded):
    assert client.post("/api/jobs", json={"index_name": "evi"}).status_code == 422
    assert client.post("/api/jobs", json={"region": "atlantis"}).status_code == 404
    assert client.post("/api/jobs", json={"dataset_id": 12345}).status_code == 404
    assert client.get("/api/jobs?status=bogus").status_code == 422
