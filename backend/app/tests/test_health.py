def test_health_ok(plain_client):
    r = plain_client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["version"]


def test_cors_allows_vite_origin(plain_client):
    r = plain_client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_system_info_has_no_secrets(client):
    r = client.get("/api/system/info")
    assert r.status_code == 200
    text = r.text.lower()
    from urllib.parse import urlsplit
    from app.core.config import get_settings
    secret = urlsplit(get_settings().database_url).password or ""  # whatever password the test database really uses
    for bad in ("database_url", "password", "postgresql+psycopg", "localhost:54", secret.lower()):
        if bad:
            assert bad not in text
    f = r.json()["features"]
    assert f["satellite_processing"]["available"] is True and "synthetic" in f["satellite_processing"]["note"]
    assert f["database"]["available"] is True and "PostGIS enabled" in f["database"]["note"]
