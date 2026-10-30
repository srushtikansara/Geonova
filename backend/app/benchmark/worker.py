"""Isolated benchmark worker: one framework per process, so memory and start-up are measured cleanly.

  python -m app.benchmark.worker pandas <input.parquet> <out_dir> <result.json> --trials 5 --warmup 1
  python -m app.benchmark.worker spark  <input.parquet> <out_dir> <result.json> --master "local[*]" ...

Timed scope per trial: read Parquet -> compute -> write Parquet (end to end, identical for both engines).
Excluded: dataset generation, framework initialisation (reported separately), warm-up runs, the post-trial
bookkeeping (output size, valid-row count). Peak memory = sampled RSS of this process tree (includes the Spark JVM).
"""
import argparse
import json
import statistics
import sys
import threading
import time
import traceback
from pathlib import Path

import psutil


class PeakRss:
    """Samples RSS of this process and all children every 50 ms (approximate; very short spikes can be missed)."""

    def __init__(self, interval=0.05):
        self.p, self.interval, self.peak, self._stop = psutil.Process(), interval, 0, threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _sample(self):
        total = 0
        for q in [self.p, *self.p.children(recursive=True)]:
            try:
                total += q.memory_info().rss
            except psutil.Error:
                pass
        self.peak = max(self.peak, total)

    def _run(self):
        while not self._stop.is_set():
            self._sample()
            time.sleep(self.interval)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join()
        self._sample()


def _dir_bytes(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())


def _bookkeeping(out_dir: Path) -> dict:
    import pyarrow.parquet as pq
    annual = pq.read_table(out_dir / "annual_summary.parquet", columns=["obs_count"]).to_pandas()
    return {"valid_rows": int(annual["obs_count"].sum()), "output_rows": int(len(annual)), "output_bytes": _dir_bytes(out_dir)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("framework", choices=("pandas", "spark"))
    ap.add_argument("input", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("result", type=Path)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--master", default="local[*]")
    ap.add_argument("--shuffle-partitions", type=int)
    ap.add_argument("--driver-memory", default="2g")
    ap.add_argument("--spark-write", default="auto")
    a = ap.parse_args(argv)
    res = {"framework": a.framework, "status": "failed", "error": None, "error_kind": None}
    try:
        with PeakRss() as mem:
            t0 = time.perf_counter()
            if a.framework == "pandas":
                from . import workload_pandas as wl
                run = lambda: wl.run(a.input, a.out_dir)  # noqa: E731
                spark = None
                init_s = time.perf_counter() - t0  # importing pandas/pyarrow
            else:
                from . import workload_spark as wl
                try:
                    spark, init_s = wl.start_spark(a.master, a.shuffle_partitions, a.driver_memory)
                except Exception as e:  # noqa: BLE001
                    res.update(error_kind="spark_unavailable", error=_short(e))
                    raise _Reported()
                res["spark_write_effective"] = wl.resolve_write_mode(a.spark_write)
                run = lambda: wl.run(spark, a.input, a.out_dir, a.spark_write)  # noqa: E731
            baseline = psutil.Process().memory_info().rss / 2**20
            for _ in range(a.warmup):
                run()
            trials = []
            for _ in range(a.trials):
                t = time.perf_counter()
                run()
                trials.append(time.perf_counter() - t)
            book = _bookkeeping(a.out_dir)
            if spark is not None:
                spark.stop()
        res.update(status="completed", init_s=init_s, trials=trials, median_s=statistics.median(trials),
                   mean_s=statistics.mean(trials), sd_s=statistics.stdev(trials) if len(trials) > 1 else None,
                   min_s=min(trials), max_s=max(trials), warmup=a.warmup, peak_rss_mb=mem.peak / 2**20,
                   baseline_rss_mb=baseline, **book)
        code = 0
    except _Reported:
        code = 3
    except MemoryError:
        res.update(error_kind="out_of_memory", error="Out of memory while running the workload."); code = 4
    except Exception as e:  # noqa: BLE001
        res.update(error_kind=res["error_kind"] or "workload_error", error=_short(e)); code = 5
        traceback.print_exc(file=sys.stderr)
    a.result.write_text(json.dumps(res))
    return code


class _Reported(Exception):
    pass


def _short(e: Exception) -> str:
    """One-line cause without local paths."""
    import re
    msg = " ".join(str(e).split())[:400] or type(e).__name__
    msg = re.sub(r"([A-Za-z]:)?[\\/][\w .\\/\-]+", "<path>", msg)
    return f"{type(e).__name__}: {msg}"


if __name__ == "__main__":
    raise SystemExit(main())
