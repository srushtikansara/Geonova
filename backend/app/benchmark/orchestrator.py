"""Run one benchmark suite: generate -> pandas worker -> spark worker -> compare. No database needed.

Each step runs in its own subprocess so that memory is attributable, the API process stays small, and a
cancel request can terminate the work immediately. Temporary input data is deleted unless keep_artifacts.
"""
import json
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import psutil

from . import compare, env
from .config import BenchmarkConfig, ConfigError, check_memory, estimate_dataset_disk_mb
from .generate import generate_dataset


class Cancelled(Exception):
    pass


def speedup(pandas_median_s: float, spark_median_s: float) -> float:
    """Speedup = Pandas time / PySpark time. > 1: PySpark was faster; < 1: Pandas was faster."""
    if pandas_median_s <= 0 or spark_median_s <= 0:
        raise ValueError("durations must be positive")
    return pandas_median_s / spark_median_s


def throughput(rows: int, seconds: float) -> float:
    """Input rows processed per second of (end-to-end) processing time."""
    if seconds <= 0:
        raise ValueError("duration must be positive")
    return rows / seconds


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run(cmd: list[str], cancel: threading.Event | None, timeout: float = 7200) -> tuple[int, str]:
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        t = 0.0
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            try:
                _, err = proc.communicate(timeout=0.5)
                return proc.returncode, err[-2000:]
            except subprocess.TimeoutExpired:
                t += 0.5
                if t > timeout:
                    raise TimeoutError("Benchmark step exceeded the time limit.")
    except BaseException:
        _kill_tree(proc)
        raise


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        p = psutil.Process(proc.pid)
        for c in p.children(recursive=True):
            c.kill()
        p.kill()
    except psutil.Error:
        pass


def check_resources(cfg: BenchmarkConfig, work_dir: Path) -> dict:
    """Raises ConfigError if memory or disk look insufficient. Returns the estimates."""
    avail = psutil.virtual_memory().available / 2**20
    ok, need = check_memory(cfg.rows, avail)
    disk_free = shutil.disk_usage(work_dir if work_dir.exists() else work_dir.parent).free / 2**20
    disk_need = estimate_dataset_disk_mb(cfg.rows) * 3
    if not ok:
        raise ConfigError(f"Estimated peak memory {need:,.0f} MB exceeds 70% of the {avail:,.0f} MB currently available. "
                          f"Choose fewer rows or free memory.")
    if disk_need > disk_free * 0.8:
        raise ConfigError(f"Estimated disk need {disk_need:,.0f} MB exceeds free space ({disk_free:,.0f} MB).")
    return {"estimated_peak_mb": need, "available_mb": avail, "estimated_disk_mb": disk_need, "disk_free_mb": disk_free}


def run_suite(cfg: BenchmarkConfig, work_dir: Path, cancel: threading.Event | None = None, log=print) -> dict:
    """Returns a plain dict describing the suite. Never raises for workload failures: they are recorded."""
    cfg.validate()
    work_dir.mkdir(parents=True, exist_ok=True)
    result = {"status": "running", "config": cfg.to_dict(), "data_kind": "synthetic", "started_at": _now(),
              "environment": env.environment(), "spark_status": env.spark_status(), "runs": {}, "comparison": None,
              "speedup": None, "error": None, "data_generation_s": None, "input_rows": None}
    inp = work_dir / "input.parquet"
    try:
        result["resources"] = check_resources(cfg, work_dir)
        log(f"generating {cfg.rows:,} synthetic rows (seed {cfg.seed}) ...")
        g = generate_dataset(inp, cfg.rows, cfg.seed, cfg.regions)
        result["data_generation_s"], result["input_rows"], result["input_bytes"] = g["seconds"], g["rows"], g["bytes"]
        outs = {}
        for fw in ("pandas", "spark"):
            if fw == "spark" and not result["spark_status"]["available"]:
                result["runs"][fw] = {"framework": fw, "status": "failed", "error_kind": "spark_unavailable",
                                      "error": "; ".join(result["spark_status"]["reasons"])}
                continue
            out_dir, res_json = work_dir / f"out_{fw}", work_dir / f"{fw}_result.json"
            for p in (out_dir, res_json):
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            cmd = [sys.executable, "-m", "app.benchmark.worker", fw, str(inp), str(out_dir), str(res_json),
                   "--trials", str(cfg.trials), "--warmup", str(cfg.warmup)]
            if fw == "spark":
                cmd += ["--master", cfg.spark_master, "--driver-memory", cfg.spark_driver_memory, "--spark-write", cfg.spark_write]
                if cfg.shuffle_partitions:
                    cmd += ["--shuffle-partitions", str(cfg.shuffle_partitions)]
            log(f"running {fw} ({cfg.warmup} warm-up + {cfg.trials} trials) ...")
            code, err = _run(cmd, cancel)
            if res_json.is_file():
                result["runs"][fw] = json.loads(res_json.read_text())
            else:
                result["runs"][fw] = {"framework": fw, "status": "failed", "error_kind": "worker_crashed",
                                      "error": f"Worker exited with code {code}: {err.strip().splitlines()[-1] if err.strip() else 'no output'}"}
            if result["runs"][fw]["status"] == "completed":
                outs[fw] = out_dir
        runs = result["runs"]
        if all(runs.get(f, {}).get("status") == "completed" for f in ("pandas", "spark")):
            result["comparison"] = compare.compare_outputs(outs["pandas"], outs["spark"])
            if result["comparison"]["passed"]:
                result["speedup"] = speedup(runs["pandas"]["median_s"], runs["spark"]["median_s"])
                result["status"] = "completed"
            else:
                result["status"] = "failed"
                result["error"] = "Numerical equivalence check FAILED; speedup is not reported. See comparison details."
        else:
            result["status"] = "failed"
            bad = [f"{f}: {r.get('error')}" for f, r in runs.items() if r.get("status") != "completed"]
            result["error"] = "; ".join(bad)
    except Cancelled:
        result["status"], result["error"] = "failed", "Cancelled by user."
    except ConfigError as e:
        result["status"], result["error"] = "failed", str(e)
    except Exception as e:  # noqa: BLE001
        result["status"], result["error"] = "failed", f"{type(e).__name__}: {str(e)[:300]}"
    finally:
        if not cfg.keep_artifacts:
            inp.unlink(missing_ok=True)  # input is deterministic from (rows, seed, regions); outputs are kept
        result["finished_at"] = _now()
    return result
