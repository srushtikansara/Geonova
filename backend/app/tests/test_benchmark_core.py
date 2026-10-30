"""Benchmark core tests. Datasets here are SYNTHETIC; tiny sizes verify logic, NOT performance."""
import json
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.benchmark import compare, config, env, generate, orchestrator, worker, workload_pandas
from app.benchmark.config import BenchmarkConfig, ConfigError

SPARK_OK = env.spark_status()["available"]
needs_spark = pytest.mark.skipif(not SPARK_OK, reason="Java/PySpark unavailable: Spark tests NOT run")


# ---------- generator ----------
def test_generator_is_deterministic_and_seed_sensitive(tmp_path):
    a, b, c = tmp_path / "a.parquet", tmp_path / "b.parquet", tmp_path / "c.parquet"
    generate.generate_dataset(a, 5000, seed=7)
    generate.generate_dataset(b, 5000, seed=7)
    generate.generate_dataset(c, 5000, seed=8)
    assert a.read_bytes() == b.read_bytes()
    assert a.read_bytes() != c.read_bytes()


def test_generator_schema_rows_labels_and_defects(tmp_path):
    p = tmp_path / "d.parquet"
    info = generate.generate_dataset(p, 20000, seed=1, regions=3)
    t = pq.read_table(p)
    assert info["rows"] == t.num_rows == 20000 and info["data_kind"] == "synthetic"
    assert t.schema.names == generate.SCHEMA.names
    assert t.schema.metadata[b"geonova_data_kind"] == b"synthetic_benchmark"
    df = t.to_pandas()
    assert df["observation_id"].tolist() == list(range(20000))
    assert set(df["region_id"]) == {"ahmedabad", "surat", "pune"}
    dates = pd.to_datetime(df["observation_date"])
    assert dates.min() >= pd.Timestamp("2021-01-01") and dates.max() <= pd.Timestamp("2025-12-31")
    assert df["ndvi"].isna().any() and (df["ndvi"].abs() > 1).any() and (df["valid_pixel_count"] == 0).any()
    assert generate.region_names(5)[3:] == ["region_004", "region_005"]


def test_generator_chunking_keeps_ids_contiguous(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "CHUNK", 700)
    p = tmp_path / "c.parquet"
    generate.generate_dataset(p, 2500, seed=3)
    ids = pq.read_table(p, columns=["observation_id"]).to_pandas()["observation_id"]
    assert ids.tolist() == list(range(2500))


# ---------- config & memory ----------
@pytest.mark.parametrize("kw", [dict(rows=10), dict(rows=config.MAX_ROWS + 1), dict(trials=0), dict(trials=31), dict(warmup=-1),
                                dict(regions=0), dict(spark_master="spark://host:7077"), dict(spark_master="yarn"),
                                dict(shuffle_partitions=0), dict(spark_driver_memory="lots"), dict(spark_write="hadoop")])
def test_invalid_configs_rejected(kw):
    with pytest.raises(ConfigError):
        BenchmarkConfig(**kw).validate()


def test_valid_config_and_local_masters():
    assert BenchmarkConfig(rows=1000, spark_master="local[4]").validate().rows == 1000
    assert BenchmarkConfig(spark_master="local[*]").validate()


def test_memory_estimate_and_refusal():
    assert config.estimate_peak_mb(5_000_000) > config.estimate_peak_mb(100_000) > config.MB_BASE
    ok, need = config.check_memory(5_000_000, available_mb=100_000)
    assert ok and need > 0
    ok, _ = config.check_memory(5_000_000, available_mb=1000)
    assert ok is False


def test_resource_check_refuses_low_memory(tmp_path, monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "virtual_memory", lambda: type("V", (), {"available": 300 * 2**20})())
    with pytest.raises(ConfigError, match="memory"):
        orchestrator.check_resources(BenchmarkConfig(rows=5_000_000), tmp_path)


# ---------- metrics ----------
def test_speedup_and_throughput_definitions():
    assert orchestrator.speedup(2.0, 1.0) == 2.0       # Spark twice as fast
    assert orchestrator.speedup(1.0, 4.0) == 0.25      # Pandas faster -> below 1
    assert orchestrator.throughput(1000, 0.5) == 2000
    with pytest.raises(ValueError):
        orchestrator.speedup(1.0, 0.0)
    with pytest.raises(ValueError):
        orchestrator.throughput(10, 0)


# ---------- workload semantics (hand-computed) ----------
def _tiny(tmp_path) -> Path:
    # region 'a': 2020-style gap handled with 2021, 2022 (consecutive) and 2024 (gap). 'b': one row.
    rows = [
        # id, region, date, ndvi, ndwi, ndbi, vpc
        (0, "a", "2021-03-01", 0.2, -0.1, 0.0, 10),
        (1, "a", "2021-06-01", 0.4, -0.3, 0.2, 30),
        (2, "a", "2022-01-01", 0.5, -0.2, 0.1, 20),
        (3, "a", "2024-01-01", 0.9, -0.2, 0.1, 10),
        (4, "a", "2021-09-01", 0.7, -0.2, 0.1, 0),       # invalid: zero pixels
        (5, "a", "2021-09-02", 1.5, -0.2, 0.1, 10),      # invalid: out of range
        (6, "a", "2021-09-03", None, -0.2, 0.1, 10),     # invalid: null
        (7, "b", "2023-05-05", 0.1, 0.0, 0.0, 5),
    ]
    df = pd.DataFrame(rows, columns=["observation_id", "region_id", "observation_date", "ndvi", "ndwi", "ndbi", "valid_pixel_count"])
    df["observation_date"] = pd.to_datetime(df["observation_date"]).dt.date
    df["valid_pixel_count"] = df["valid_pixel_count"].astype("int32")
    p = tmp_path / "tiny.parquet"
    pq.write_table(pa.Table.from_pandas(df, schema=generate.SCHEMA, preserve_index=False), p)
    return p


def _check_tiny(out: Path):
    ann = compare.read_table(out / "annual_summary.parquet").sort_values(["region_id", "year"]).reset_index(drop=True)
    assert ann[["region_id", "year", "obs_count", "valid_pixel_sum"]].values.tolist() == [
        ["a", 2021, 2, 40], ["a", 2022, 1, 20], ["a", 2024, 1, 10], ["b", 2023, 1, 5]]
    r = ann.iloc[0]
    assert r["mean_ndvi"] == pytest.approx(0.3) and r["mean_ndwi"] == pytest.approx(-0.2) and r["mean_ndbi"] == pytest.approx(0.1)
    assert r["std_ndvi"] == pytest.approx(np.std([0.2, 0.4], ddof=1))  # sample SD
    assert r["min_ndvi"] == 0.2 and r["max_ndvi"] == 0.4
    assert r["weighted_mean_ndvi"] == pytest.approx((0.2 * 10 + 0.4 * 30) / 40)
    assert np.isnan(ann.iloc[1]["std_ndvi"])  # one observation -> undefined sample SD
    reg = compare.read_table(out / "regional_summary.parquet").sort_values("region_id").reset_index(drop=True)
    assert reg[["region_id", "obs_count", "valid_pixel_sum"]].values.tolist() == [["a", 4, 70], ["b", 1, 5]]
    assert reg.iloc[0]["mean_ndvi"] == pytest.approx(np.mean([0.2, 0.4, 0.5, 0.9]))  # over raw rows, not mean of annual means
    chg = compare.read_table(out / "annual_change.parquet").sort_values(["region_id", "year"]).reset_index(drop=True)
    assert np.isnan(chg.loc[0, "delta_mean_ndvi"])                               # first year: no previous
    assert chg.loc[1, "delta_mean_ndvi"] == pytest.approx(0.5 - 0.3)             # 2022 - 2021 (consecutive)
    assert np.isnan(chg.loc[2, "delta_mean_ndvi"])                               # 2024 after 2022: gap -> not compared
    assert np.isnan(chg.loc[3, "delta_mean_ndvi"])


def test_pandas_workload_known_values(tmp_path):
    workload_pandas.run(_tiny(tmp_path), tmp_path / "out")
    _check_tiny(tmp_path / "out")


@needs_spark
@pytest.mark.spark
def test_spark_workload_known_values_and_equivalence(tmp_path):
    from app.benchmark import workload_spark
    p = _tiny(tmp_path)
    spark, init_s = workload_spark.start_spark("local[2]", 2, "1g")
    try:
        workload_spark.run(spark, p, tmp_path / "out_s")
        _check_tiny(tmp_path / "out_s")
        # equivalence on a larger synthetic file, in both Spark write modes
        g = tmp_path / "g.parquet"
        generate.generate_dataset(g, 30000, seed=11)
        workload_pandas.run(g, tmp_path / "out_p")
        modes = ["collect", "auto"] + (["native"] if not workload_spark._is_windows() or workload_spark.winutils_present() else [])
        for mode in modes:  # explicit 'native' is only tried where Spark's native local write can work
            res = workload_spark.run(spark, g, tmp_path / f"out_{mode}", mode)
            assert res["write_mode"] in ("native", "collect")
            rep = compare.compare_outputs(tmp_path / "out_p", tmp_path / f"out_{mode}")
            assert rep["passed"], rep["errors"] or [k for k, v in rep["columns"].items() if not v["passed"]]
            assert rep["max_abs_err"] < 1e-9
    finally:
        spark.stop()
    assert init_s > 0


def test_spark_write_mode_resolution(monkeypatch, tmp_path):
    from app.benchmark import workload_spark as ws
    monkeypatch.delenv("HADOOP_HOME", raising=False)
    monkeypatch.setattr(ws, "_is_windows", lambda: True)
    assert ws.resolve_write_mode("auto") == "collect"          # Windows without winutils: labelled fallback
    assert ws.resolve_write_mode("native") == "native"          # explicit choices are respected
    assert ws.resolve_write_mode("collect") == "collect"
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "winutils.exe").write_bytes(b"")
    monkeypatch.setenv("HADOOP_HOME", str(tmp_path))
    assert ws.resolve_write_mode("auto") == "native"            # winutils present: native writer
    monkeypatch.setattr(ws, "_is_windows", lambda: False)
    assert ws.resolve_write_mode("auto") == "native"


# ---------- numerical comparison ----------
def _write_outputs(d: Path, annual: pd.DataFrame, regional=None, change=None):
    d.mkdir(parents=True, exist_ok=True)
    annual.to_parquet(d / "annual_summary.parquet", index=False)
    (regional if regional is not None else annual.drop(columns="year")).to_parquet(d / "regional_summary.parquet", index=False)
    (change if change is not None else annual[["region_id", "year"]].assign(delta_mean_ndvi=[np.nan, 0.1])).to_parquet(d / "annual_change.parquet", index=False)


def _ann(**over):
    df = pd.DataFrame({"region_id": ["a", "a"], "year": [2021, 2022], "obs_count": [5, 7], "valid_pixel_sum": [50, 70],
                       "mean_ndvi": [0.3, 0.4]})
    for k, v in over.items():
        df[k] = v
    return df


def test_compare_passes_identical_and_within_tolerance(tmp_path):
    _write_outputs(tmp_path / "p", _ann())
    _write_outputs(tmp_path / "s", _ann(mean_ndvi=[0.3 + 1e-13, 0.4 - 1e-13]))
    r = compare.compare_outputs(tmp_path / "p", tmp_path / "s")
    assert r["passed"] is True and 0 < r["max_abs_err"] < 1e-12 and r["mae"] > 0
    assert r["columns"]["annual_summary.obs_count"]["rule"] == "exact"


def test_compare_fails_on_float_beyond_tolerance_and_reports_it(tmp_path):
    _write_outputs(tmp_path / "p", _ann())
    _write_outputs(tmp_path / "s", _ann(mean_ndvi=[0.3, 0.4001]))
    r = compare.compare_outputs(tmp_path / "p", tmp_path / "s")
    assert r["passed"] is False
    assert r["columns"]["annual_summary.mean_ndvi"]["passed"] is False and r["max_abs_err"] == pytest.approx(1e-4, rel=1e-6)


def test_compare_counts_must_match_exactly(tmp_path):
    _write_outputs(tmp_path / "p", _ann())
    _write_outputs(tmp_path / "s", _ann(obs_count=[5, 8]))
    r = compare.compare_outputs(tmp_path / "p", tmp_path / "s")
    assert r["passed"] is False and r["columns"]["annual_summary.obs_count"]["passed"] is False


def test_compare_null_pattern_and_keys(tmp_path):
    _write_outputs(tmp_path / "p", _ann())
    _write_outputs(tmp_path / "s", _ann(mean_ndvi=[np.nan, 0.4]))
    assert compare.compare_outputs(tmp_path / "p", tmp_path / "s")["passed"] is False
    other = _ann()
    other["region_id"] = ["a", "b"]
    _write_outputs(tmp_path / "k", other)
    r = compare.compare_outputs(tmp_path / "p", tmp_path / "k")
    assert r["passed"] is False and r["errors"]


def test_compare_sorts_before_comparing(tmp_path):
    _write_outputs(tmp_path / "p", _ann())
    _write_outputs(tmp_path / "s", _ann().iloc[::-1].reset_index(drop=True))
    assert compare.compare_outputs(tmp_path / "p", tmp_path / "s")["columns"]["annual_summary.obs_count"]["passed"] is True


# ---------- worker + orchestrator failure reporting ----------
def test_worker_pandas_reports_trials_and_metrics(tmp_path):
    inp = tmp_path / "in.parquet"
    generate.generate_dataset(inp, 3000, seed=2)
    res = tmp_path / "r.json"
    assert worker.main(["pandas", str(inp), str(tmp_path / "out"), str(res), "--trials", "3", "--warmup", "1"]) == 0
    r = json.loads(res.read_text())
    assert r["status"] == "completed" and len(r["trials"]) == 3 and r["warmup"] == 1
    assert r["min_s"] <= r["median_s"] <= r["max_s"] and r["init_s"] >= 0 and r["peak_rss_mb"] > 0
    assert 0 < r["valid_rows"] < 3000 and r["output_rows"] > 0 and r["output_bytes"] > 0  # filter removed the defects


def test_worker_spark_start_failure_is_reported_not_substituted(tmp_path, monkeypatch):
    from app.benchmark import workload_spark
    monkeypatch.setattr(workload_spark, "start_spark", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Java gateway process exited before sending its port number")))
    inp = tmp_path / "in.parquet"
    generate.generate_dataset(inp, 500, seed=2)
    res = tmp_path / "r.json"
    assert worker.main(["spark", str(inp), str(tmp_path / "out"), str(res)]) == 3
    r = json.loads(res.read_text())
    assert r["status"] == "failed" and r["error_kind"] == "spark_unavailable" and "Java gateway" in r["error"]
    assert "median_s" not in r and not (tmp_path / "out" / "annual_summary.parquet").exists()  # no fake metrics, no pandas fallback


def test_suite_records_spark_unavailable_without_fake_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(env, "spark_status", lambda: {"available": False, "pyspark": None, "java": {"found": False},
                                                       "reasons": ["Java was not found."]})
    res = orchestrator.run_suite(BenchmarkConfig(rows=1000, trials=2, warmup=0), tmp_path / "w", log=lambda *_: None)
    assert res["status"] == "failed" and "Java was not found" in res["error"]
    assert res["runs"]["pandas"]["status"] == "completed"           # the real Pandas measurement is kept
    sp = res["runs"]["spark"]
    assert sp["status"] == "failed" and "median_s" not in sp and res["speedup"] is None and res["comparison"] is None
    assert not (tmp_path / "w" / "input.parquet").exists()          # temporary input cleaned up
    assert res["data_generation_s"] > 0 and res["input_rows"] == 1000


def test_suite_cancellation_cleans_up(tmp_path):
    ev = threading.Event()
    ev.set()
    res = orchestrator.run_suite(BenchmarkConfig(rows=1000, trials=1, warmup=0), tmp_path / "w", cancel=ev, log=lambda *_: None)
    assert res["status"] == "failed" and res["error"] == "Cancelled by user."
    assert not (tmp_path / "w" / "input.parquet").exists()


def test_suite_rejects_invalid_config(tmp_path):
    bad = BenchmarkConfig(rows=1000, spark_master="spark://x:7077")
    with pytest.raises(ConfigError):
        orchestrator.run_suite(bad, tmp_path / "w", log=lambda *_: None)


def test_environment_report_has_versions():
    e = env.environment()
    assert e["python"] and e["pandas"] and e["pyarrow"] and "cpu_logical" in e
    st = env.spark_status()
    assert set(st) == {"available", "pyspark", "java", "reasons"}


def test_java_major_parsing(monkeypatch):
    import subprocess as sp
    for out, major in (('openjdk version "21.0.12.1" 2026-08-18', 21), ('java version "1.8.0_391"', 8), ('openjdk version "17.0.9" 2023-10-17', 17)):
        monkeypatch.setattr(sp, "run", lambda *a, _o=out, **k: type("R", (), {"stderr": _o})())
        monkeypatch.setattr(env.shutil, "which", lambda n: "/usr/bin/java")
        monkeypatch.delenv("JAVA_HOME", raising=False)
        assert env.java_info()["major"] == major
