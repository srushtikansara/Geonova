from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import schemas as s
from app.db import models as m
from app.core.errors import NotFound
from . import regions as regions_svc
from ._conv import dataset_out


def list_datasets(db: Session, region: str | None, status: str | None, limit: int, offset: int):
    q = select(m.Dataset).options(joinedload(m.Dataset.region))
    if region:
        q = q.join(m.Region).where(m.Region.code == region.lower())
    if status:
        q = q.where(m.Dataset.status == status)
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    rows = db.scalars(q.order_by(m.Dataset.acquisition_date.desc(), m.Dataset.id).limit(limit).offset(offset)).unique()
    return [dataset_out(d) for d in rows], total


def get_dataset(db: Session, dataset_id: int) -> s.DatasetOut:
    d = db.scalar(select(m.Dataset).options(joinedload(m.Dataset.region)).where(m.Dataset.id == dataset_id))
    if d is None:
        raise NotFound(f"Dataset {dataset_id} not found")
    return dataset_out(d)


def create_dataset(db: Session, data: s.DatasetCreate) -> s.DatasetOut:
    region = regions_svc.get_orm(db, data.region)  # 404 if the region code is unknown
    d = m.Dataset(name=data.name, source=data.source, mission=data.mission, sensor=data.sensor,
                  acquisition_date=data.acquisition_date, region_id=region.id, status=data.status,
                  processing_baseline=data.processing_baseline, extra=data.metadata)
    db.add(d)
    db.commit()
    db.refresh(d)
    return dataset_out(d)
