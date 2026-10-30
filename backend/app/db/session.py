"""Engine and session management. Nothing here creates tables."""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


class DatabaseUnavailable(Exception):
    """Raised when no database is configured or it cannot be reached."""


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    if not url:
        raise DatabaseUnavailable("DATABASE_URL is not configured")
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5,
                         connect_args={"connect_timeout": 5})


@lru_cache
def _sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request; rollback on any error; always closed."""
    session = _sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> tuple[bool, str]:
    """Return (ok, short message). Never includes the connection URL or password."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            has_postgis = conn.execute(text("SELECT count(*) FROM pg_extension WHERE extname='postgis'")).scalar()
        return (True, "Connected; PostGIS enabled.") if has_postgis else (True, "Connected; PostGIS extension missing.")
    except DatabaseUnavailable as e:
        return False, str(e)
    except Exception:
        return False, "Database is not reachable."


def new_session() -> Session:
    """A standalone session for background workers (the caller must close it)."""
    return _sessionmaker()()
