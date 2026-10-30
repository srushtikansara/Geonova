from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_writes
from app.db.session import get_db
from app.schemas import Region, RegionCreate, RegionList
from app.services import regions as svc

router = APIRouter(prefix="/regions", tags=["regions"])


@router.get("", response_model=RegionList)
def list_regions(db: Session = Depends(get_db)) -> RegionList:
    items = svc.list_regions(db)
    note = ("'configured' means metadata exists. 'analysed' is true only when real results exist."
            if items else "No regions in the database. Run: python -m app.db.seed")
    return RegionList(items=items, count=len(items), note=note)


@router.get("/{region_id}", response_model=Region)
def get_region(region_id: str, db: Session = Depends(get_db)) -> Region:
    return svc.get_region(db, region_id)


@router.post("", response_model=Region, status_code=201, dependencies=[Depends(require_writes)])
def create_region(body: RegionCreate, db: Session = Depends(get_db)) -> Region:
    return svc.create_region(db, body)
