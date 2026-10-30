"""Benchmark API tests (test database). run_suite is replaced by a FAKE returning canned dicts in the
mock-based tests, so the numbers in them are test fixtures, NOT measurements. One test runs the real
Pandas path end to end on a tiny SYNTHETIC dataset."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.benchmark import env, orchestrator, runner
from app.db import models as m


def _trial_run(median, status="completed", error=None):
    if status != "completed":
        return {"framework": "x", "status": "failed", "error": error, "error_kind": "spark_unavailable"}
    return {"status": "completed", "trials": [median * 1.1, median, median * 0.9], "warmup": 1, "median_s": median,
            "mean_s": median, "sd_s": 0.01, "min_s": median * 0.9, "max_s": median * 1.1, "init_s": 0.5, "peak_rss_mb": 123.0,
            "baseline_rss_mb": 50.0, "valid_rows": 900, "output_rows": 30, "output_bytes": 4096}


def _fake(status="completed", spark_ok=True, passed=True):
    def run_suite(cfg, work_dir, cancel=None, log=None):
        now = datetime.now(timezone.utc).isoformat()
        cmp_ = {"passed": passed, "mae": 1e-15, "max_abs_err": 2e-15, "columns": {}, "errors": []} if spark_ok else None
        return {"status": status if spark_ok else "failed", "error": None if spark_ok and passed else ("Outputs differ." if spark_ok else "Java was not found."),
                "input_rows": cfg.rows, "data_generation_s": 0.25, "speedup": 2.0 if spark_ok and passed else None,
                "comparison": cmp_, "environment": {"python": "3.x"}, "spark_status": {"available": spark_ok},
                "resources": {}, "config": cfg.to_dict(), "started_at": now, "finished_at": now,
                "runs": {"pandas": _trial_run(1.0), "spark": _trial_run(0.5) if spark_ok else _trial_run(0, "failed", "Java was not found.")}}
    return run_suite


@pytest.fixture(autouse=True)
def _bench_dir(tmp_path, monkeypatch):
    import app.benchmark.paths as paths
    monkeypatch.setattr(paths, "bench_root", lambda: tmp_path / "bench")
    monkeypatch.setattr("app.services.benchmarks.bench_root", lambda: tmp_path / "bench")
    monkeypatch.setattr(runner, "bench_root", lambda: tmp_path / "bench")


def _post(client, **kw):
    return client.post("/api/benchmarks", json={"rows": 1000, "trials": 3, "warmup": 1, **kw})


def test_empty_state(client):
    r = client.get("/api/benchmarks").json()
    assert r["items"] == [] and r["suites"] == [] and r["count"] == 0 and "No benchmarks" in r["note"]


@pytest.mark.parametrize("body", [{"rows": 50}, {"rows": 30_000_000}, {"rows": 1000, "trials": 0}, {"rows": 1000, "trials": 99},
                                  {"rows": 1000, "spark_master": "spark://h:7077"}, {"rows": 1000, "spark_write": "hdfs"},
                                  {"rows": "many"}, {"rows": 1000, "warmup": -1}, {"rows": 1000, "regions": 0}])
def test_invalid_requests_rejected_and_nothing_stored(client, db, body):
    assert client.post("/api/benchmarks", json=body).status_code == 422
    assert db.scalar(select(func.count()).select_from(m.BenchmarkSuite)) == 0


def test_large_run_requires_confirmation(client, db, monkeypatch):
    monkeypatch.setattr(orchestrator, "run_suite", _fake())
    r = _post(client, rows=1_000_000)
    assert r.status_code == 422 and "confirm" in r.text
    assert db.scalar(select(func.count()).select_from(m.BenchmarkSuite)) == 0
    assert _post(client, rows=1_000_000, confirm=True).status_code == 202


def test_refuses_when_memory_insufficient(client, monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "virtual_memory", lambda: type("V", (), {"available": 200 * 2**20, "total": 8 * 2**30})())
    r = _post(client, rows=500_000)
    assert r.status_code == 422 and "memory" in r.text.lower()


def test_completed_suite_is_stored_and_returned(client, db, monkeypatch):
    monkeypatch.setattr(orchestrator, "run_suite", _fake())
    r = _post(client)
    assert r.status_code == 202
    sid = r.json()["id"]
    s = client.get(f"/api/benchmarks/{sid}").json()
    assert s["status"] == "completed" and s["speedup"] == 2.0 and s["input_rows"] == 1000 and s["data_generation_s"] == 0.25
    assert {x["framework"] for x in s["runs"]} == {"pandas", "spark"}
    sp = next(x for x in s["runs"] if x["framework"] == "spark")
    pd_ = next(x for x in s["runs"] if x["framework"] == "pandas")
    assert sp["median_s"] == 0.5 and len(sp["trial_durations"]) == 3 and sp["within_tolerance"] is True
    assert sp["throughput"] == pytest.approx(1000 / 0.5) and pd_["throughput"] == pytest.approx(1000 / 1.0)
    assert sp["data_kind"] == "synthetic"
    lst = client.get("/api/benchmarks").json()
    assert lst["count"] == 2 and len(lst["suites"]) == 1 and lst["items"][0]["benchmark_id"] == sid
    one = client.get(f"/api/benchmarks/runs/{sp['id']}").json()
    assert one["framework"] == "spark"
    assert db.scalar(select(func.count()).select_from(m.Artifact).where(m.Artifact.benchmark_run_id.is_not(None))) == 2


def test_failed_spark_is_recorded_without_fake_metrics(client, monkeypatch):
    monkeypatch.setattr(orchestrator, "run_suite", _fake(spark_ok=False))
    sid = _post(client).json()["id"]
    s = client.get(f"/api/benchmarks/{sid}").json()
    assert s["status"] == "failed" and "Java" in s["error_details"] and s["speedup"] is None
    sp = next(x for x in s["runs"] if x["framework"] == "spark")
    assert sp["status"] == "failed" and sp["median_s"] is None and sp["throughput"] is None and sp["trial_durations"] is None
    assert next(x for x in s["runs"] if x["framework"] == "pandas")["status"] == "completed"


def test_mismatch_is_marked_failed_not_hidden(client, monkeypatch):
    monkeypatch.setattr(orchestrator, "run_suite", _fake(status="failed", passed=False))
    s = client.get(f"/api/benchmarks/{_post(client).json()['id']}").json()
    assert s["status"] == "failed" and s["speedup"] is None
    assert next(x for x in s["runs"] if x["framework"] == "spark")["within_tolerance"] is False


def test_unexpected_crash_recorded_generic_error(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret /path/leak")
    monkeypatch.setattr(orchestrator, "run_suite", boom)
    s = client.get(f"/api/benchmarks/{_post(client).json()['id']}").json()
    assert s["status"] == "failed" and "secret" not in (s["error_details"] or "") and s["runs"] == []


def test_not_found_and_cancel(client, db, monkeypatch):
    assert client.get("/api/benchmarks/999").status_code == 404
    assert client.get("/api/benchmarks/runs/999").status_code == 404
    assert client.post("/api/benchmarks/999/cancel").status_code == 404
    monkeypatch.setattr(runner, "submit", lambda sid: None)  # keep it queued
    sid = _post(client).json()["id"]
    assert client.get(f"/api/benchmarks/{sid}").json()["status"] == "queued"
    c = client.post(f"/api/benchmarks/{sid}/cancel").json()
    assert c["status"] == "failed" and c["error_details"] == "Cancelled by user."


def test_preflight_starts_nothing(client, db):
    p = client.get("/api/benchmarks/preflight?rows=1000000").json()
    assert p["requires_confirmation"] is True and p["estimated_peak_mb"] > 0 and p["available_mb"] > 0
    assert "available" in p["spark"] and client.get("/api/benchmarks/preflight?rows=10").status_code == 422
    assert db.scalar(select(func.count()).select_from(m.BenchmarkSuite)) == 0
    assert client.get("/api/benchmarks/preflight?rows=1000").json()["requires_confirmation"] is False


def test_api_start_runs_nothing(client, db):
    """Creating the app / listing never executes a benchmark."""
    client.get("/api/benchmarks")
    assert db.scalar(select(func.count()).select_from(m.BenchmarkSuite)) == 0


def test_real_pandas_end_to_end_with_spark_unavailable(client, monkeypatch):
    """No fake: real generator + real Pandas subprocess; Spark reported unavailable (simulated) -> failed, not substituted."""
    monkeypatch.setattr(env, "spark_status", lambda: {"available": False, "pyspark": None, "java": {"found": False}, "reasons": ["Java was not found."]})
    sid = _post(client, rows=2000, trials=2, warmup=0).json()["id"]
    s = client.get(f"/api/benchmarks/{sid}").json()
    assert s["status"] == "failed" and "Java" in s["error_details"]
    pd_ = next(x for x in s["runs"] if x["framework"] == "pandas")
    assert pd_["status"] == "completed" and pd_["row_count"] == 2000 and len(pd_["trial_durations"]) == 2 and pd_["median_s"] > 0
    assert all(x["framework"] != "spark" or x["median_s"] is None for x in s["runs"])


@pytest.mark.spark
@pytest.mark.skipif(not env.spark_status()["available"], reason="Java/PySpark unavailable: Spark API test NOT run")
def test_real_spark_end_to_end(client):
    sid = _post(client, rows=2000, trials=2, warmup=1, shuffle_partitions=2).json()["id"]
    s = client.get(f"/api/benchmarks/{sid}").json()
    assert s["status"] == "completed", s["error_details"]
    sp = next(x for x in s["runs"] if x["framework"] == "spark")
    assert sp["within_tolerance"] is True and s["speedup"] == pytest.approx(
        next(x for x in s["runs"] if x["framework"] == "pandas")["median_s"] / sp["median_s"])
