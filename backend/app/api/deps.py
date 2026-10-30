from fastapi import HTTPException

from app.core.config import get_settings, writes_enabled


def require_writes() -> None:
    if not writes_enabled(get_settings()):
        raise HTTPException(status_code=403, detail="Write endpoints are disabled in this environment.")
