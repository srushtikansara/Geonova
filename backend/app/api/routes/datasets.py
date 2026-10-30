from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_writes
from app.db.session import get_db
from app.schemas import DatasetCreate, DatasetList, DatasetOut, DatasetStatus
from app.services import datasets as svc

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("", response_model=DatasetList)
def list_datasets(region: str | None = Query(None, description="Region code"),
                  status: DatasetStatus | None = None,
                  limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db)) -> DatasetList:
    items, total = svc.list_datasets(db, region, status, limit, offset)
    note = f"{total} dataset(s) match." if total else "No datasets have been ingested yet."
    return DatasetList(items=items, count=total, note=note)


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)) -> DatasetOut:
    return svc.get_dataset(db, dataset_id)


@router.post("", response_model=DatasetOut, status_code=201, dependencies=[Depends(require_writes)])
def create_dataset(body: DatasetCreate, db: Session = Depends(get_db)) -> DatasetOut:
    return svc.create_dataset(db, body)
