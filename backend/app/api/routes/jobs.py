from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_writes
from app.db.session import get_db
from app.schemas import Job, JobCreate, JobList, JobStatus
from app.services import jobs as svc

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobList)
def list_jobs(status: JobStatus | None = None, limit: int = Query(100, ge=1, le=500),
              offset: int = Query(0, ge=0), db: Session = Depends(get_db)) -> JobList:
    items, total = svc.list_jobs(db, status, limit, offset)
    return JobList(items=items, count=total)


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: str, db: Session = Depends(get_db)) -> Job:
    return svc.get_job(db, job_id)


@router.post("", response_model=Job, status_code=201, dependencies=[Depends(require_writes)])
def create_job(body: JobCreate, db: Session = Depends(get_db)) -> Job:
    """Creates a job record. 'scene_processing' and 'change_detection' jobs run in a background worker;
    other job types are stored as queued only. Poll GET /api/jobs/{id} for status and result."""
    return svc.submit_if_runnable(db, svc.create_job(db, body))
