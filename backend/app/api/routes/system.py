import platform
from importlib.util import find_spec

from fastapi import APIRouter

from app.core.config import get_settings, writes_enabled
from app.db.session import check_database
from app.schemas import FeatureStatus, SystemInfo

router = APIRouter(prefix="/system", tags=["system"])


def _installed(mod: str) -> bool:
    return find_spec(mod) is not None


def _rasterio_ok() -> bool:
    try:
        import rasterio  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


@router.get("/info", response_model=SystemInfo)
def info() -> SystemInfo:
    s = get_settings()
    db_ok, db_note = check_database()
    from app.benchmark.env import spark_status
    sp = spark_status()
    features = {
        "regions_metadata": FeatureStatus(available=True, note="Configured example regions only."),
        "satellite_processing": FeatureStatus(available=_rasterio_ok(), note="Implemented; verified on synthetic test rasters only. No real Sentinel-2 product has been processed yet."),
        "database": FeatureStatus(available=db_ok, note=db_note),
        "write_endpoints": FeatureStatus(available=writes_enabled(s), note="POST endpoints for regions, datasets and jobs."),
        "pyspark_benchmarks": FeatureStatus(available=sp["available"],
                                            note="Pandas vs PySpark (local mode)." + ("" if sp["available"] else " " + " ".join(sp["reasons"]))),
    }
    # Only non-secret values are returned: no DATABASE_URL, no file paths.
    return SystemInfo(app_name=s.app_name, version=s.app_version, environment=s.app_env,
                      python_version=platform.python_version(), cors_origins=s.cors_origins, features=features)
