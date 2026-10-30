"""Import MEASURED benchmark rows from the Phase-2 harness CSV:
    python -m app.db.import_benchmarks path/to/benchmark.csv
Expected columns: engine, master, records, data, runs, mean_s, sd_s, min_s, peak_driver_rss_mb
Speedup is computed only when both engines were measured on the same row count.
"""
import csv
import math
import platform
import sys

from sqlalchemy.orm import Session

from app.db import models as m
from app.db.session import get_engine


def _f(v):
    try:
        x = float(v)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def import_csv(db: Session, path: str) -> int:
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    runs = []
    for r in rows:
        n, mean = int(float(r["records"])), _f(r["mean_s"])
        runs.append(m.BenchmarkRun(
            framework=r["engine"], workload="regional_stats", data_kind=r.get("data", "synthetic"),
            row_count=n, duration_s=mean, duration_sd_s=_f(r.get("sd_s")), runs=int(float(r["runs"])) if r.get("runs") else None,
            throughput_rows_s=(n / mean) if mean else None,
            environment={"master": r.get("master"), "python": platform.python_version(), "os": platform.platform(),
                         "peak_driver_rss_mb": _f(r.get("peak_driver_rss_mb")), "memory_note": "Python driver only, not the Spark JVM"},
            status="completed"))
    db.add_all(runs)
    db.flush()
    pandas = {(b.row_count, b.environment.get("master")): b for b in runs if b.framework == "pandas"}
    for b in runs:
        base = pandas.get((b.row_count, b.environment.get("master")))
        if b.framework == "spark" and base and base.duration_s and b.duration_s:
            b.speedup, b.baseline_run_id = base.duration_s / b.duration_s, base.id
    db.commit()
    return len(runs)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    with Session(get_engine()) as db:
        print(f"imported {import_csv(db, sys.argv[1])} runs")
