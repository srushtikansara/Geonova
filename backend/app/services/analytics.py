from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas as s
from app.core.errors import Invalid
from app.db import models as m
from . import regions as regions_svc


def summary(db: Session, include_synthetic: bool = False) -> s.AnalyticsSummary:
    regions_n, scenes_n = db.execute(
        select(func.count(func.distinct(m.RegionalAnalytic.region_id)),
               func.count(func.distinct(m.RegionalAnalytic.dataset_id)))
        .join(m.Dataset, m.Dataset.id == m.RegionalAnalytic.dataset_id)
        .where(True if include_synthetic else regions_svc.real_data_filter())).one()
    if not regions_n:
        return s.AnalyticsSummary(available=False, reason="No analysis has been run yet.")
    return s.AnalyticsSummary(available=True, regions_analysed=regions_n, scenes_processed=scenes_n)


def temporal(db: Session, index: str, region: str | None, date_from: date | None, date_to: date | None,
             include_synthetic: bool = False) -> s.TemporalSeries:
    if date_from and date_to and date_from > date_to:
        raise Invalid("date_from must not be after date_to")
    q = (select(m.RegionalAnalytic, m.Region.code).join(m.Region, m.Region.id == m.RegionalAnalytic.region_id)
         .join(m.Dataset, m.Dataset.id == m.RegionalAnalytic.dataset_id).where(m.RegionalAnalytic.index_name == index))
    if not include_synthetic:
        q = q.where(regions_svc.real_data_filter())
    if region:
        q = q.where(m.Region.id == regions_svc.get_orm(db, region).id)  # 404 for unknown region
    if date_from:
        q = q.where(m.RegionalAnalytic.observation_date >= date_from)
    if date_to:
        q = q.where(m.RegionalAnalytic.observation_date <= date_to)
    rows = db.execute(q.order_by(m.RegionalAnalytic.observation_date)).all()
    if not rows:
        return s.TemporalSeries(available=False, region=region, index=index, reason="No temporal results exist for this selection.")
    if not region and len({code for _, code in rows}) > 1:
        return s.TemporalSeries(available=False, region=None, index=index,
                                reason="Results exist for several regions. Select a region to see one time series.")
    pts = [{"date": a.observation_date.isoformat(), "value": a.mean, "mean": a.mean, "min": a.minimum,
            "max": a.maximum, "std": a.std_dev, "valid_pixels": a.valid_pixel_count,
            "dataset_id": a.dataset_id, "region": code} for a, code in rows]
    return s.TemporalSeries(available=True, region=region or rows[0][1], index=index, points=pts)


def regional(db: Session, region: str | None, include_synthetic: bool = False) -> s.RegionalSummaryList:
    """Per region and index: number of observations, the latest observation's statistics, and latest-minus-earliest mean."""
    q = (select(m.RegionalAnalytic, m.Region.code, m.Dataset.extra["data_kind"].astext)
         .join(m.Region, m.Region.id == m.RegionalAnalytic.region_id)
         .join(m.Dataset, m.Dataset.id == m.RegionalAnalytic.dataset_id))
    if not include_synthetic:
        q = q.where(regions_svc.real_data_filter())
    if region:
        q = q.where(m.Region.id == regions_svc.get_orm(db, region).id)  # 404 for unknown region
    groups: dict[tuple[str, str], list] = {}
    for a, code, kind in db.execute(q.order_by(m.RegionalAnalytic.observation_date)).all():
        groups.setdefault((code, a.index_name), []).append((a, kind))
    if not groups:
        return s.RegionalSummaryList(available=False, includes_synthetic=include_synthetic,
                                     reason="No regional results exist for this selection.")
    items = []
    for (code, idx), rows in sorted(groups.items()):
        first, (last, _) = rows[0][0], rows[-1]
        cov = (last.valid_pixel_count / last.total_pixel_count) if last.total_pixel_count else None
        delta = (last.mean - first.mean) if len(rows) > 1 and last.mean is not None and first.mean is not None else None
        items.append(s.RegionalIndexSummary(
            region=code, index=idx, observations=len(rows), first_date=first.observation_date, last_date=last.observation_date,
            latest_mean=last.mean, latest_min=last.minimum, latest_max=last.maximum, latest_std=last.std_dev,
            latest_valid_pixels=last.valid_pixel_count, latest_total_pixels=last.total_pixel_count, latest_coverage=cov,
            change_first_to_last=delta, synthetic_fixture=any(k == "synthetic_test_fixture" for _, k in rows)))
    return s.RegionalSummaryList(available=True, items=items, includes_synthetic=include_synthetic)
