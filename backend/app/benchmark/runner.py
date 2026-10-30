"""Background execution of benchmark suites with database tracking. One suite at a time."""
import logging
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.core.config import get_settings
from app.db import models as m
from app.db.session import new_session
from . import orchestrator
from .config import BenchmarkConfig
from .paths import bench_root

log = logging.getLogger("geonova.benchmark")
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="geonova-bench")
_cancel: dict[int, threading.Event] = {}


def submit(suite_id: int) -> None:
    if get_settings().jobs_run_inline:
        run_suite_job(suite_id)
    else:
        _executor.submit(run_suite_job, suite_id)


def request_cancel(suite_id: int) -> None:
    ev = _cancel.get(suite_id)
    if ev:
        ev.set()


def _dt(iso):
    return datetime.fromisoformat(iso) if iso else None


def run_suite_job(suite_id: int) -> None:
    db = new_session()
    ev = _cancel.setdefault(suite_id, threading.Event())
    try:
        suite = db.get(m.BenchmarkSuite, suite_id)
        if suite is None or suite.status != "queued":
            return
        suite.status, suite.started_at = "running", datetime.now(timezone.utc)
        db.commit()
        cfg = BenchmarkConfig(**suite.config)
        work = bench_root() / f"suite-{suite_id}"
        try:
            res = orchestrator.run_suite(cfg, work, ev)
            _persist(db, suite, res)
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("benchmark %s crashed", suite_id)
            suite = db.get(m.BenchmarkSuite, suite_id)
            suite.status, suite.error_details = "failed", "Unexpected benchmark error. See the server log."
            suite.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        _cancel.pop(suite_id, None)
        db.close()


def _persist(db, suite: m.BenchmarkSuite, res: dict) -> None:
    suite.status = res["status"]
    suite.error_details = res["error"] if res["status"] == "failed" else None
    if res["status"] == "failed" and not suite.error_details:
        suite.error_details = "Benchmark failed."
    suite.input_rows, suite.data_generation_s = res.get("input_rows"), res.get("data_generation_s")
    suite.speedup, suite.comparison = res.get("speedup"), res.get("comparison")
    suite.environment = {**res["environment"], "spark_prerequisites": res["spark_status"],
                         "resources_estimate": res.get("resources")}
    suite.started_at, suite.finished_at = _dt(res["started_at"]), _dt(res["finished_at"])
    cmp_ = res.get("comparison") or {}
    base_id = None
    for fw in ("pandas", "spark"):
        r = res["runs"].get(fw)
        if not r or not suite.input_rows:
            continue
        ok = r.get("status") == "completed"
        run = m.BenchmarkRun(
            suite_id=suite.id, framework=fw, workload=suite.workload, data_kind="synthetic",
            dataset_size_label=f"{suite.requested_rows:,}", row_count=suite.input_rows,
            duration_s=r.get("mean_s"), duration_sd_s=r.get("sd_s"), median_s=r.get("median_s"), min_s=r.get("min_s"),
            max_s=r.get("max_s"), runs=len(r["trials"]) if ok else None, trial_durations=r.get("trials"),
            init_s=r.get("init_s"), valid_rows=r.get("valid_rows"), output_rows=r.get("output_rows"),
            output_bytes=r.get("output_bytes"), peak_rss_mb=r.get("peak_rss_mb"),
            throughput_rows_s=(suite.input_rows / r["median_s"]) if ok and r.get("median_s") else None,
            speedup=suite.speedup if fw == "spark" else None, baseline_run_id=base_id if fw == "spark" and suite.speedup else None,
            mae=cmp_.get("mae") if fw == "spark" else None, max_abs_err=cmp_.get("max_abs_err") if fw == "spark" else None,
            within_tolerance=cmp_.get("passed") if fw == "spark" and cmp_ else None,
            environment={**res["environment"], "warmup": r.get("warmup"), "baseline_rss_mb": r.get("baseline_rss_mb"),
                         "spark_master": res["config"]["spark_master"] if fw == "spark" else None,
                         "spark_write": (r.get("spark_write_effective") or res["config"]["spark_write"]) if fw == "spark" else None,
                         "spark_write_requested": res["config"]["spark_write"] if fw == "spark" else None,
                         "shuffle_partitions": res["config"].get("shuffle_partitions") if fw == "spark" else None,
                         "memory_note": "sampled RSS of the worker process tree (includes the Spark JVM); approximate"},
            status="completed" if ok else "failed",
            error_details=None if ok else (r.get("error") or "failed")[:1000],
            started_at=suite.started_at, finished_at=suite.finished_at)
        db.add(run)
        db.flush()
        if fw == "pandas":
            base_id = run.id
        if ok:
            db.add(m.Artifact(artifact_type="table", file_format="parquet",
                              storage_ref=f"benchmarks/suite-{suite.id}/out_{fw}", benchmark_run_id=run.id,
                              extra={"kind": "benchmark_output", "data_kind": "synthetic"}))
    db.commit()
