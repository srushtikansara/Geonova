from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analytics, benchmarks, datasets, health, jobs, rasters, regions, system
from app.core.config import get_settings
from app.core.errors import register_handlers


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version=s.app_version,
                  description="GEONOVA backend: regions, datasets, processing jobs, analytics and Pandas-vs-PySpark benchmarks (PostgreSQL/PostGIS).")
    register_handlers(app)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST"], allow_headers=["*"])
    api = APIRouter(prefix="/api")
    for r in (health.router, system.router, regions.router, datasets.router,
              analytics.router, benchmarks.router, jobs.router, rasters.router):
        api.include_router(r)
    app.include_router(api)
    return app


app = create_app()
