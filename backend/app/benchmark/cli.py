"""No-database development mode: python -m app.benchmark.cli --rows 100000 --trials 3
Writes result.json (+ output Parquet) under <data_dir>/benchmarks/cli-<timestamp>/ and prints a summary."""
import argparse
import json
from datetime import datetime
from pathlib import Path

from .paths import bench_root
from .config import BenchmarkConfig, ConfigError
from .orchestrator import run_suite


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=int, default=100_000)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--regions", type=int, default=3)
    ap.add_argument("--master", default="local[*]")
    ap.add_argument("--spark-write", default="auto", choices=("auto", "native", "collect"))
    ap.add_argument("--driver-memory", default="2g")
    ap.add_argument("--confirm-large", action="store_true", help="required for 1,000,000+ rows")
    ap.add_argument("--keep-input", action="store_true")
    a = ap.parse_args(argv)
    try:
        cfg = BenchmarkConfig(rows=a.rows, trials=a.trials, warmup=a.warmup, seed=a.seed, regions=a.regions,
                              spark_master=a.master, spark_write=a.spark_write, spark_driver_memory=a.driver_memory,
                              keep_artifacts=a.keep_input).validate()
        from .config import LARGE_ROWS
        if cfg.rows >= LARGE_ROWS and not a.confirm_large:
            raise ConfigError("Runs of 1,000,000+ rows need --confirm-large (they take minutes and use GBs of RAM).")
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 2
    wd = bench_root() / f"cli-{datetime.now():%Y%m%d-%H%M%S}"
    res = run_suite(cfg, wd)
    (wd / "result.json").write_text(json.dumps(res, indent=2, default=str))
    for fw, r in res["runs"].items():
        if r.get("status") == "completed":
            print(f"{fw:7s} median {r['median_s']:.3f}s  (min {r['min_s']:.3f}, max {r['max_s']:.3f}, n={len(r['trials'])})  init {r['init_s']:.2f}s  peak RSS {r['peak_rss_mb']:.0f} MB")
        else:
            print(f"{fw:7s} FAILED: {r.get('error')}")
    if res["comparison"]:
        c = res["comparison"]
        print(f"equivalence: {'PASS' if c['passed'] else 'FAIL'}  mae={c['mae']:.3g} max_abs_err={c['max_abs_err']:.3g}")
    print(f"speedup (pandas/spark): {res['speedup']:.3f}" if res["speedup"] else "speedup: not available")
    print(f"status: {res['status']}" + (f" - {res['error']}" if res["error"] else ""))
    print(f"details: {wd / 'result.json'}")
    return 0 if res["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
