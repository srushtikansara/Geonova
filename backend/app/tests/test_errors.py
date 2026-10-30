from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app


def test_database_down_gives_503_without_leaking(monkeypatch):
    def broken():
        raise OperationalError("SELECT 1", {}, Exception("connection to server at 127.0.0.1 port 5432 failed: password=secret"))
        yield

    app.dependency_overrides[get_db] = broken
    try:
        r = TestClient(app).get("/api/regions")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 503
    assert "secret" not in r.text and "127.0.0.1" not in r.text


def test_health_works_without_database(monkeypatch):
    import app.db.session as sess
    monkeypatch.setattr(sess, "get_engine", lambda: (_ for _ in ()).throw(sess.DatabaseUnavailable("DATABASE_URL is not configured")))
    c = TestClient(app)
    assert c.get("/api/health").status_code == 200
    f = c.get("/api/system/info").json()["features"]["database"]
    assert f["available"] is False and "not configured" in f["note"]


def test_unconfigured_database_gives_503(monkeypatch):
    import app.db.session as sess
    sess._sessionmaker.cache_clear()
    monkeypatch.setattr(sess, "get_engine", lambda: (_ for _ in ()).throw(sess.DatabaseUnavailable("DATABASE_URL is not configured")))
    r = TestClient(app).get("/api/regions")
    sess._sessionmaker.cache_clear()
    assert r.status_code == 503 and "DATABASE_URL" not in r.text


def test_writes_disabled_returns_403(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        r = client.post("/api/regions", json={"code": "x", "name": "X", "bbox": [0, 0, 1, 1]})
        assert r.status_code == 403
        assert client.get("/api/regions").status_code == 200  # reads still work
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
