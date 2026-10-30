"""Region service (database-backed)."""
from geoalchemy2.elements import WKTElement
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app import schemas as s
from app.core.errors import NotFound
from app.db import models as m
from ._conv import region_out


def bbox_wkt(b: list[float]) -> WKTElement:
    x0, y0, x1, y1 = b
    return WKTElement(f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))", srid=4326)


def real_data_filter():
    """Rows whose dataset is not explicitly a synthetic test fixture (older rows without a marker count as real)."""
    return func.coalesce(m.Dataset.extra["data_kind"].astext, "observation") != "synthetic_test_fixture"


def _analysed_ids(db: Session) -> set[int]:
    q = (select(m.RegionalAnalytic.region_id).join(m.Dataset, m.Dataset.id == m.RegionalAnalytic.dataset_id)
         .where(real_data_filter()).distinct())
    return set(db.scalars(q))


def list_regions(db: Session) -> list[s.Region]:
    done = _analysed_ids(db)
    return [region_out(r, r.id in done) for r in db.scalars(select(m.Region).order_by(m.Region.name))]


def get_orm(db: Session, code: str) -> m.Region:
    r = db.scalar(select(m.Region).where(m.Region.code == code.lower()))
    if r is None:
        raise NotFound(f"Region '{code}' not found")
    return r


def get_region(db: Session, code: str) -> s.Region:
    r = get_orm(db, code)
    return region_out(r, r.id in _analysed_ids(db))


def create_region(db: Session, data: s.RegionCreate) -> s.Region:
    r = m.Region(code=data.code, name=data.name, state=data.state, country=data.country,
                 description=data.description, min_lon=data.bbox[0], min_lat=data.bbox[1],
                 max_lon=data.bbox[2], max_lat=data.bbox[3], geom=bbox_wkt(data.bbox))
    db.add(r)
    db.commit()  # IntegrityError (duplicate code) is mapped to HTTP 409 by the error handler
    return region_out(r)
