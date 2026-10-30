"""Experiment B: timing harness. Warm-up, n repeated runs, mean/SD.

Timings include the aggregation only (data already in memory/Parquet); say
exactly what is included when you report numbers. Nothing is hard-coded:
every number in the report must come from the CSV this writes.
"""
import argparse
import os
import statistics
import tempfile
import time

import pandas as pd
import psutil

from . import analysis_pandas as ap
from .synth import synthetic_records


def _rss_mb():
    return psutil.Process(os.getpid()).memory_info().rss / 2**20


def run(sizes, runs, warmup, master, out_csv, real_parquet=None):
    from . import analysis_spark as asp
    spark = asp.get_spark(master)
    rows = []
    for n in sizes:
        if real_parquet:
            df = pd.read_parquet(real_parquet).head(n)
            data_kind = "real"
        else:
            df = synthetic_records(n, seed=1)
            data_kind = "synthetic"
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rec.parquet")
            df.to_parquet(path)
            for engine in ("pandas", "spark"):
                def once():
                    t0 = time.perf_counter()
                    if engine == "pandas":
                        ap.region_stats(pd.read_parquet(path))
                    else:
                        asp.region_stats(spark, path)
                    return time.perf_counter() - t0
                for _ in range(warmup):
                    once()
                times, rss = [], []
                for _ in range(runs):
                    times.append(once())
                    rss.append(_rss_mb())
                rows.append({"engine": engine, "master": master, "records": len(df), "data": data_kind,
                             "runs": runs, "mean_s": statistics.mean(times),
                             "sd_s": statistics.stdev(times) if runs > 1 else float("nan"),
                             "min_s": min(times), "peak_driver_rss_mb": max(rss)})
                print(rows[-1])
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    return rows


if __name__ == "__main__":
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--sizes", type=int, nargs="+", default=[100_000, 1_000_000, 5_000_000])
    ap_.add_argument("--runs", type=int, default=10)
    ap_.add_argument("--warmup", type=int, default=2)
    ap_.add_argument("--master", default="local[*]")
    ap_.add_argument("--real-parquet", default=None)
    ap_.add_argument("--out", default="outputs/benchmark.csv")
    a = ap_.parse_args()
    run(a.sizes, a.runs, a.warmup, a.master, a.out, a.real_parquet)
