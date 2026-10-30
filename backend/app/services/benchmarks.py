from datetime import datetime, timezone

import psutil
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import schemas as s
from app.benchmark import env as benv
from app.benchmark.config import LARGE_ROWS, BenchmarkConfig, ConfigError, check_memory, estimate_dataset_disk_mb
from app.benchmark.orchestrator import check_resources
from app.benchmark.paths import bench_root
from app.core.errors import Invalid, NotFound
from app.db import models as m
from ._conv import benchmark_out, suite_out


def list_benchmarks(db: Session, limit: int, offset: int):
    total = db.scalar(select(func.count()).select_from(m.BenchmarkRun))
    rows = db.scalars(select(m.BenchmarkRun).order_by(m.BenchmarkRun.row_count, m.BenchmarkRun.framework, m.BenchmarkRun.id)
                      .limit(limit).offset(offset))
    suites = db.scalars(select(m.BenchmarkSuite).options(selectinload(m.BenchmarkSuite.runs))
                        .order_by(m.BenchmarkSuite.id.desc()).limit(100))
    return [benchmark_out(b) for b in rows], total, [suite_out(x) for x in suites]


def get_benchmark(db: Session, run_id: int) -> s.BenchmarkOut:
    b = db.get(m.BenchmarkRun, run_id)
    if b is None:
        raise NotFound(f"Benchmark run {run_id} not found")
    return benchmark_out(b)


def get_suite(db: Session, suite_id: int) -> s.SuiteOut:
    x = db.scalar(select(m.BenchmarkSuite).options(selectinload(m.BenchmarkSuite.runs)).where(m.BenchmarkSuite.id == suite_id))
    if x is None:
        raise NotFound(f"Benchmark {suite_id} not found")
    return suite_out(x, with_runs=True)


def preflight(rows: int) -> s.Preflight:
    avail = psutil.virtual_memory().available / 2**20
    ok, need = check_memory(rows, avail)
    return s.Preflight(rows=rows, estimated_peak_mb=need, available_mb=avail, estimated_disk_mb=estimate_dataset_disk_mb(rows) * 3,
                       memory_ok=ok, requires_confirmation=rows >= LARGE_ROWS, spark=benv.spark_status(),
                       environment=benv.environment(),
                       note="Estimates are heuristics. Nothing is started by this call.")


def create_suite(db: Session, req: s.BenchmarkRequest) -> s.SuiteOut:
    """Validate, check resources, and store a QUEUED benchmark. Nothing is executed here."""
    cfg = BenchmarkConfig(rows=req.rows, trials=req.trials, warmup=req.warmup, seed=req.seed, regions=req.regions,
                          spark_master=req.spark_master, shuffle_partitions=req.shuffle_partitions,
                          spark_driver_memory=req.spark_driver_memory, spark_write=req.spark_write,
                          keep_artifacts=req.keep_artifacts)
    try:
        cfg.validate()
        if cfg.rows >= LARGE_ROWS and not req.confirm:
            raise ConfigError("Runs of 1,000,000 rows or more are expensive; resend with confirm=true.")
        bench_root().mkdir(parents=True, exist_ok=True)
        check_resources(cfg, bench_root())
    except ConfigError as e:
        raise Invalid(str(e))
    x = m.BenchmarkSuite(status="queued", requested_rows=cfg.rows, trials=cfg.trials, warmup=cfg.warmup, seed=cfg.seed,
                         config=cfg.to_dict())
    db.add(x)
    db.commit()
    return get_suite(db, x.id)


def cancel_suite(db: Session, suite_id: int) -> s.SuiteOut:
    from app.benchmark import runner
    x = db.get(m.BenchmarkSuite, suite_id)
    if x is None:
        raise NotFound(f"Benchmark {suite_id} not found")
    if x.status == "queued":
        x.status, x.error_details, x.finished_at = "failed", "Cancelled by user.", datetime.now(timezone.utc)
        db.commit()
    elif x.status == "running":
        runner.request_cancel(suite_id)  # the worker thread records the final state
    return get_suite(db, suite_id)
