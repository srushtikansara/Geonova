from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas import Health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health)
def health() -> Health:
    s = get_settings()
    return Health(status="ok", service=s.app_name, version=s.app_version, time_utc=datetime.now(timezone.utc))
