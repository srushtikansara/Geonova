"""Test setup. Tests run ONLY against TEST_DATABASE_URL (database name must end with _test).
The real DATABASE_URL is never used: it is overwritten in this process before the app imports."""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

BACKEND = Path(__file__).resolve().parents[2]


def _load_urls():
    from app.core.config import Settings
    s = Settings()  # reads env + .env
    return s.database_url, os.environ.get("TEST_DATABASE_URL") or s.test_database_url


_real_url, TEST_URL = _load_urls()
_dbname = urlparse(TEST_URL).path.lstrip("/") if TEST_URL else ""
if TEST_URL:
    if not _dbname.endswith("_test"):
        pytest.exit("TEST_DATABASE_URL must point to a database whose name ends with '_test'.", returncode=2)
    if _real_url and urlparse(_real_url).path == urlparse(TEST_URL).path and urlparse(_real_url).hostname == urlparse(TEST_URL).hostname:
        pytest.exit("TEST_DATABASE_URL must differ from DATABASE_URL.", returncode=2)
os.environ["DATABASE_URL"] = TEST_URL  # the app under test can only ever see the test database
os.environ["APP_ENV"] = "development"
os.environ.pop("API_WRITES_ENABLED", None)
# Processing tests: temp data dir; synthetic fixtures may be persisted ONLY in the test database; jobs run inline.
import tempfile  # noqa: E402

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="geonova_test_data_")
os.environ["ALLOW_SYNTHETIC_PERSIST"] = "true"
os.environ["JOBS_RUN_INLINE"] = "true"

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


def _alembic(*args):
    return subprocess.run([sys.executable, "-m", "alembic", "-x", f"db_url={TEST_URL}", *args], cwd=BACKEND,
                          capture_output=True, text=True)


@pytest.fixture(scope="session")
def engine():
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL is not set: PostgreSQL integration tests were NOT run.")
    eng = create_engine(TEST_URL)
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Test database unreachable ({type(e).__name__}): integration tests NOT run.")
    r = _alembic("upgrade", "head")
    assert r.returncode == 0, r.stderr[-800:]
    yield eng
    _alembic("downgrade", "base")
    eng.dispose()


@pytest.fixture()
def db(engine):
    with engine.begin() as c:
        names = [r[0] for r in c.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('alembic_version','spatial_ref_sys')"))]
        c.execute(text(f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE"))
    s = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)()
    yield s
    s.close()


@pytest.fixture()
def client(db, engine):
    maker = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    def _get_db():
        s = maker()
        try:
            yield s
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded(db):
    from app.db.seed import seed_regions
    seed_regions(db)
    return db


@pytest.fixture()
def plain_client():
    """No database fixture: for tests that must not need PostgreSQL."""
    return TestClient(app)
