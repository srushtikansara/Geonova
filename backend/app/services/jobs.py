import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import schemas as s
from app.core.errors import NotFound
from app.db import models as m
from app.core.errors import Invalid
from app.processing import runner
from app.processing.errors import InputError
from . import regions as regions_svc
from ._conv import job_out

_OPTS = (joinedload(m.AnalysisJob.region),)


def list_jobs(db: Session, status: str | None, limit: int, offset: int):
    q = select(m.AnalysisJob).options(*_OPTS)
    if status:
        q = q.where(m.AnalysisJob.status == status)
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    rows = db.scalars(q.order_by(m.AnalysisJob.created_at.desc()).limit(limit).offset(offset)).unique()
    return [job_out(j) for j in rows], total


def get_job(db: Session, job_id: str) -> s.Job:
    try:
        uid = uuid.UUID(job_id)
    except ValueError:
        raise NotFound(f"Job '{job_id}' not found")  # malformed ids are simply not found
    j = db.scalar(select(m.AnalysisJob).options(*_OPTS).where(m.AnalysisJob.id == uid))
    if j is None:
        raise NotFound(f"Job '{job_id}' not found")
    return job_out(j)


def create_job(db: Session, data: s.JobCreate) -> s.Job:
    """Queue a job record. No processing runs in this phase, so it stays 'queued'."""
    region_id = regions_svc.get_orm(db, data.region).id if data.region else None
    if data.dataset_id is not None and db.get(m.Dataset, data.dataset_id) is None:
        raise NotFound(f"Dataset {data.dataset_id} not found")
    _validate_runnable(db, data)
    j = m.AnalysisJob(job_type=data.job_type, region_id=region_id, dataset_id=data.dataset_id,
                      index_name=data.index_name, status="queued", params=data.params)
    db.add(j)
    db.commit()
    return get_job(db, str(j.id))


def _validate_runnable(db: Session, data: s.JobCreate) -> None:
    """Fast, synchronous checks for job types that have a runner. Other types are stored as queued only."""
    if data.job_type not in runner.RUNNABLE:
        return
    if not data.region:
        raise Invalid("A region code is required for this job type.")
    p = data.params
    if data.job_type == "scene_processing":
        try:
            d = runner.data_paths().resolve_ref(str(p.get("scene_path", "")), runner.data_paths().raw)
        except InputError as e:
            raise Invalid(f"scene_path: {e}")
        if not d.is_dir():
            raise Invalid("scene_path: scene directory not found under the raw data directory.")
    else:
        if not data.index_name:
            raise Invalid("index_name is required for change_detection.")
        for key in ("earlier_dataset_id", "later_dataset_id"):
            if not isinstance(p.get(key), int):
                raise Invalid(f"params.{key} (integer dataset id) is required.")
            if db.get(m.Dataset, p[key]) is None:
                raise NotFound(f"Dataset {p[key]} not found")
        if p["earlier_dataset_id"] == p["later_dataset_id"]:
            raise Invalid("Earlier and later datasets must differ.")


def submit_if_runnable(db: Session, job: s.Job) -> s.Job:
    """Hand the queued job to the background worker (never blocks on raster work)."""
    if job.kind not in runner.RUNNABLE:
        return job
    runner.submit(job.id)
    db.expire_all()
    return get_job(db, job.id)
