from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_writes
from app.benchmark import runner
from app.db.session import get_db
from app.schemas import BenchmarkList, BenchmarkOut, BenchmarkRequest, Preflight, SuiteOut
from app.services import benchmarks as svc

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


@router.get("", response_model=BenchmarkList)
def list_benchmarks(limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                    db: Session = Depends(get_db)) -> BenchmarkList:
    """Measured per-framework runs (`items`, unchanged shape) plus the benchmark suites that group them."""
    items, total, suites = svc.list_benchmarks(db, limit, offset)
    note = (f"{total} measured run(s) in {len(suites)} benchmark(s). All data is SYNTHETIC."
            if total or suites else "No benchmarks have been run yet.")
    return BenchmarkList(items=items, count=total, suites=suites, note=note)


@router.get("/preflight", response_model=Preflight)
def preflight(rows: int = Query(100_000, ge=100, le=20_000_000)) -> Preflight:
    """Memory/disk estimate and Spark prerequisites for a planned run. Starts nothing."""
    return svc.preflight(rows)


@router.get("/runs/{run_id}", response_model=BenchmarkOut)
def get_run(run_id: int, db: Session = Depends(get_db)) -> BenchmarkOut:
    return svc.get_benchmark(db, run_id)


@router.post("", response_model=SuiteOut, status_code=202, dependencies=[Depends(require_writes)])
def create_benchmark(body: BenchmarkRequest, db: Session = Depends(get_db)) -> SuiteOut:
    """Queue a Pandas-vs-PySpark benchmark on a generated SYNTHETIC dataset. Returns immediately (202);
    poll GET /api/benchmarks/{id}. Runs of 1,000,000+ rows need confirm=true. Never started automatically."""
    suite = svc.create_suite(db, body)
    runner.submit(suite.id)
    db.expire_all()
    return svc.get_suite(db, suite.id)


@router.get("/{benchmark_id}", response_model=SuiteOut)
def get_benchmark(benchmark_id: int, db: Session = Depends(get_db)) -> SuiteOut:
    return svc.get_suite(db, benchmark_id)


@router.post("/{benchmark_id}/cancel", response_model=SuiteOut, dependencies=[Depends(require_writes)])
def cancel_benchmark(benchmark_id: int, db: Session = Depends(get_db)) -> SuiteOut:
    return svc.cancel_suite(db, benchmark_id)
