from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import AnalyticsSummary, IndexName, RegionalSummaryList, TemporalSeries
from app.services import analytics as svc

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
def summary(include_synthetic: bool = Query(False, description="Include synthetic test fixtures (never real observations)"),
            db: Session = Depends(get_db)) -> AnalyticsSummary:
    return svc.summary(db, include_synthetic)


@router.get("/regional", response_model=RegionalSummaryList)
def regional(region: str | None = Query(None, description="Region code, e.g. 'pune'"),
             include_synthetic: bool = Query(False, description="Include synthetic test fixtures (never real observations)"),
             db: Session = Depends(get_db)) -> RegionalSummaryList:
    """Per region and index: observation count, latest statistics and latest-minus-earliest mean change."""
    return svc.regional(db, region, include_synthetic)


@router.get("/temporal", response_model=TemporalSeries)
def temporal(index: IndexName = Query("ndvi", description="Spectral index"),
             region: str | None = Query(None, description="Region code, e.g. 'pune'"),
             date_from: date | None = None, date_to: date | None = None,
             include_synthetic: bool = Query(False, description="Include synthetic test fixtures (never real observations)"),
             db: Session = Depends(get_db)) -> TemporalSeries:
    return svc.temporal(db, index, region, date_from, date_to, include_synthetic)
