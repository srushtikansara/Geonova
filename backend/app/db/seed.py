"""Idempotent seed of the configured example regions: python -m app.db.seed"""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app import schemas as s
from app.db import models as m
from app.db.session import get_engine
from app.services import regions as svc

DATA = Path(__file__).resolve().parent.parent / "data" / "regions.json"


def seed_regions(db: Session) -> tuple[int, int]:
    added = updated = 0
    for r in json.loads(DATA.read_text(encoding="utf-8")):
        body = s.RegionCreate(code=r["id"], name=r["name"], state=r.get("state", ""), country=r.get("country", ""),
                              description=r.get("notes", ""), bbox=r["bbox"])
        row = db.query(m.Region).filter_by(code=body.code).one_or_none()
        if row is None:
            db.add(m.Region(code=body.code, name=body.name, state=body.state, country=body.country,
                            description=body.description, min_lon=body.bbox[0], min_lat=body.bbox[1],
                            max_lon=body.bbox[2], max_lat=body.bbox[3], geom=svc.bbox_wkt(body.bbox)))
            added += 1
        else:
            row.name, row.state, row.country, row.description = body.name, body.state, body.country, body.description
            row.min_lon, row.min_lat, row.max_lon, row.max_lat = body.bbox
            row.geom = svc.bbox_wkt(body.bbox)
            updated += 1
    db.commit()
    return added, updated


if __name__ == "__main__":
    with Session(get_engine()) as db:
        a, u = seed_regions(db)
    print(f"regions: {a} added, {u} updated")
