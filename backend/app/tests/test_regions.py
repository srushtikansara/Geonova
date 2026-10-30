def test_empty_database(client):
    body = client.get("/api/regions").json()
    assert body["count"] == 0 and body["items"] == []


def test_regions_list_after_seed(client, seeded):
    body = client.get("/api/regions").json()
    assert body["count"] == 4
    assert {x["name"] for x in body["items"]} == {"Ahmedabad", "Surat", "Pune", "Bengaluru"}
    for x in body["items"]:  # Phase 1 response shape preserved
        assert x["configured"] is True and x["analysed"] is False
        assert len(x["bbox"]) == 4 and {"id", "state", "country", "notes"} <= set(x)


def test_region_detail_and_404(client, seeded):
    assert client.get("/api/regions/pune").json()["name"] == "Pune"
    assert client.get("/api/regions/PUNE").status_code == 200
    assert client.get("/api/regions/atlantis").status_code == 404


def test_seed_is_idempotent(client, seeded):
    from app.db.seed import seed_regions
    assert seed_regions(seeded) == (0, 4)
    assert client.get("/api/regions").json()["count"] == 4


REGION = {"code": "rajkot", "name": "Rajkot", "state": "Gujarat", "country": "India", "bbox": [70.7, 22.2, 70.9, 22.4]}


def test_create_region_and_duplicate(client):
    r = client.post("/api/regions", json=REGION)
    assert r.status_code == 201 and r.json()["id"] == "rajkot" and r.json()["analysed"] is False
    assert client.post("/api/regions", json=REGION).status_code == 409


def test_create_region_validation(client):
    assert client.post("/api/regions", json={**REGION, "bbox": [71, 22, 70, 23]}).status_code == 422  # min>=max
    assert client.post("/api/regions", json={**REGION, "bbox": [70, 22, 71]}).status_code == 422
    assert client.post("/api/regions", json={**REGION, "code": "Bad Code!"}).status_code == 422
    assert client.post("/api/regions", json={**REGION, "bbox": [-200, 22, 70, 23]}).status_code == 422