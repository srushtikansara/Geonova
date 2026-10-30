import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import models as m
from app.db.seed import seed_regions
from app.db.session import check_database, get_db
from app.services import regions as svc
from .conftest import BACKEND, TEST_URL


def test_connection_and_postgis(engine):
    with engine.connect() as c:
        assert c.execute(text("SELECT 1")).scalar() == 1
        assert c.execute(text("SELECT PostGIS_Version()")).scalar()
    assert check_database() == (True, "Connected; PostGIS enabled.")


def test_session_dependency_rolls_back_and_closes(engine):
    gen = get_db()
    s = next(gen)
    s.add(m.Region(code="tmp", name="Tmp", min_lon=0, min_lat=0, max_lon=1, max_lat=1, geom=svc.bbox_wkt([0, 0, 1, 1])))
    s.flush()
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))
    with engine.connect() as c:  # nothing was committed
        assert c.execute(text("SELECT count(*) FROM regions WHERE code='tmp'")).scalar() == 0


def test_geometry_and_spatial_query(db):
    seed_regions(db)
    # A point inside the configured Pune box is contained; a point in Ahmedabad is not.
    inside = db.execute(text("SELECT code FROM regions WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(73.85, 18.52), 4326))")).scalars().all()
    assert inside == ["pune"]
    assert db.execute(text("SELECT ST_SRID(geom) FROM regions LIMIT 1")).scalar() == 4326
    idx = db.execute(text("SELECT indexdef FROM pg_indexes WHERE tablename='regions' AND indexname='idx_regions_geom'")).scalar()
    assert idx and "gist" in idx.lower()


def test_unique_region_code_constraint(db):
    seed_regions(db)
    db.add(m.Region(code="pune", name="Dup", min_lon=0, min_lat=0, max_lon=1, max_lat=1, geom=svc.bbox_wkt([0, 0, 1, 1])))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_bbox_check_constraint(db):
    db.add(m.Region(code="bad", name="Bad", min_lon=5, min_lat=0, max_lon=1, max_lat=1, geom=svc.bbox_wkt([1, 0, 5, 1])))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_foreign_key_enforced(db):
    from datetime import date
    db.add(m.Dataset(name="x", source="s", mission="Sentinel-2", sensor="MSI", acquisition_date=date(2023, 1, 1), region_id=999))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_cascade_delete_region_removes_datasets(db):
    from datetime import date
    seed_regions(db)
    r = svc.get_orm(db, "pune")
    db.add(m.Dataset(name="x", source="s", mission="Sentinel-2", sensor="MSI", acquisition_date=date(2023, 1, 1), region_id=r.id))
    db.commit()
    db.delete(r)
    db.commit()
    assert db.query(m.Dataset).count() == 0


def test_failed_job_requires_error_details(db):
    db.add(m.AnalysisJob(job_type="regional_analysis", status="failed"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(m.AnalysisJob(job_type="regional_analysis", status="failed", error_details="out of memory"))
    db.commit()


def test_migrations_match_models(engine):
    """`alembic check` reports no difference between the ORM models and the migration."""
    r = subprocess.run([sys.executable, "-m", "alembic", "-x", f"db_url={TEST_URL}", "check"], cwd=BACKEND, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]
