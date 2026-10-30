"""Job execution + API integration, using SYNTHETIC scenes (not real observations) and the TEST database."""
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db import models as m
from app.processing import cli, runner
from .synthetic_scene import make_scene, scene_bbox_wgs84

REGION = {"code": "synthville", "name": "Synthville", "bbox": scene_bbox_wgs84()}
S1, S2 = "S2X_SYNTH_20230115T050209", "S2X_SYNTH_20240115T050209"


@pytest.fixture(autouse=True)
def clean_data_dir():
    """Each test starts with an empty temporary data directory."""
    import shutil
    root = runner.data_paths().root
    for sub in ("raw", "processed"):
        shutil.rmtree(root / sub, ignore_errors=True)
    runner.data_paths()
    yield


@pytest.fixture()
def region(client):
    assert client.post("/api/regions", json=REGION).status_code == 201


def _scene(name=S1, **kw):
    return make_scene(runner.data_paths().raw / "synthville", name, **kw)


def _job(client, **body):
    return client.post("/api/jobs", json={"job_type": "scene_processing", "region": "synthville",
                                          "params": {"scene_path": f"synthville/{S1}"}, **body})


def test_scene_job_completes_and_persists(client, region, db):
    _scene(cloud_patch=True)
    r = _job(client)
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["status"] == "completed" and j["started_utc"] and j["completed_utc"] and j["error_details"] is None
    res = j["result"]
    assert res["data_kind"] == "synthetic_test_fixture" and set(res["indices"]) == {"ndvi", "ndwi", "ndbi"}
    assert any("SYNTHETIC" in x for x in res["limitations"])
    root = runner.data_paths().root
    for v in res["indices"].values():
        assert (root / v["raster_ref"]).is_file() and not v["raster_ref"].startswith("/")
    assert (root / res["summary_ref"]).is_file()
    # database records
    ds = client.get("/api/datasets?region=synthville").json()["items"]
    assert len(ds) == 1 and ds[0]["status"] == "processed" and ds[0]["metadata"]["data_kind"] == "synthetic_test_fixture"
    assert db.scalar(select(func.count()).select_from(m.Artifact)) == 4  # 3 GeoTIFF + 1 Parquet
    assert db.scalar(select(func.count()).select_from(m.RegionalAnalytic)) == 3
    assert client.get(f"/api/jobs/{j['id']}").json()["result"]["dataset_id"] == ds[0]["id"]


def test_synthetic_results_are_not_reported_as_real_analysis(client, region):
    _scene()
    assert _job(client).json()["status"] == "completed"
    reg = client.get("/api/regions/synthville").json()
    assert reg["analysed"] is False  # synthetic fixture must not mark a region as analysed
    assert client.get("/api/analytics/summary").json()["available"] is False
    t = client.get("/api/analytics/temporal?index=ndvi&region=synthville").json()
    assert t["available"] is False
    t2 = client.get("/api/analytics/temporal?index=ndvi&region=synthville&include_synthetic=true").json()
    assert t2["available"] is True and t2["points"][0]["valid_pixels"] > 0 and t2["points"][0]["date"] == "2023-01-15"


def test_real_observation_marks_region_analysed(client, region):
    _scene(data_kind="observation")  # metadata says observation: a stand-in to exercise the logic, still generated data
    assert _job(client).json()["status"] == "completed"
    assert client.get("/api/regions/synthville").json()["analysed"] is True
    assert client.get("/api/analytics/summary").json() == {"available": True, "regions_analysed": 1, "scenes_processed": 1, "reason": None}


def test_rerun_is_idempotent(client, region, db):
    _scene()
    assert _job(client).json()["status"] == "completed"
    assert _job(client).json()["status"] == "completed"
    assert db.scalar(select(func.count()).select_from(m.RegionalAnalytic)) == 3
    assert db.scalar(select(func.count()).select_from(m.Artifact)) == 4
    assert db.scalar(select(func.count()).select_from(m.Dataset)) == 1


def test_synthetic_not_persisted_when_disallowed(client, region, monkeypatch):
    _scene()
    monkeypatch.setenv("ALLOW_SYNTHETIC_PERSIST", "false")
    get_settings.cache_clear()
    try:
        j = _job(client).json()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert j["status"] == "failed" and "Synthetic" in j["error_details"]
    assert client.get("/api/datasets").json()["count"] == 0


def test_failure_missing_band_is_recorded_without_paths(client, region):
    _scene(omit=("B11",))
    j = _job(client).json()
    assert j["status"] == "failed" and "B11" in j["error_details"]
    assert "/" not in j["error_details"].replace("B03_10m.tif / T43QCF_20230115T050209_B03_10m.jp2", "")
    assert str(runner.data_paths().root) not in j["error_details"]
    assert j["completed_utc"] and j["result"] == {}


def test_failure_missing_mask_and_unknown_offset(client, region):
    _scene(with_scl=False)
    assert "cloud mask" in _job(client).json()["error_details"]
    d = _scene(name="S2X_SYNTH_20230301T050209", manifest=False)
    j = client.post("/api/jobs", json={"job_type": "scene_processing", "region": "synthville",
                                       "params": {"scene_path": f"synthville/{d.name}"}}).json()
    assert j["status"] == "failed" and "offset" in j["error_details"]


def test_unexpected_error_is_generic(client, region, monkeypatch):
    _scene()
    def boom(*a, **k):
        raise RuntimeError("secret /home/user/passwords.txt")
    monkeypatch.setattr(runner, "process_scene", boom)
    j = _job(client).json()
    assert j["status"] == "failed" and "secret" not in j["error_details"] and "Unexpected" in j["error_details"]


def test_job_submission_validation(client, region):
    base = {"job_type": "scene_processing", "region": "synthville"}
    assert client.post("/api/jobs", json={**base, "params": {"scene_path": "../etc"}}).status_code == 422
    assert client.post("/api/jobs", json={**base, "params": {"scene_path": "/etc/passwd"}}).status_code == 422
    assert client.post("/api/jobs", json={**base, "params": {"scene_path": "synthville/missing"}}).status_code == 422
    assert client.post("/api/jobs", json={**base, "params": {}}).status_code == 422
    assert client.post("/api/jobs", json={"job_type": "scene_processing", "params": {"scene_path": "x"}}).status_code == 422
    assert client.post("/api/jobs", json={"job_type": "change_detection", "region": "synthville"}).status_code == 422
    assert client.get("/api/jobs").json()["count"] == 0  # nothing was created for invalid requests


def test_change_detection_job(client, region):
    _scene(S1)
    _scene(S2, scale=0.6)
    d1 = _job(client).json()["result"]["dataset_id"]
    d2 = client.post("/api/jobs", json={"job_type": "scene_processing", "region": "synthville",
                                        "params": {"scene_path": f"synthville/{S2}"}}).json()["result"]["dataset_id"]
    body = {"job_type": "change_detection", "region": "synthville", "index_name": "ndvi",
            "params": {"earlier_dataset_id": d1, "later_dataset_id": d2, "threshold": 0.05}}
    j = client.post("/api/jobs", json=body).json()
    assert j["status"] == "completed", j
    s = j["result"]["summary"]
    assert s["prop_negative"] == pytest.approx(1.0) and s["mean"] < 0 and s["valid_pixel_count"] > 0
    assert "not a validated land-cover" in j["result"]["interpretation"]
    assert (runner.data_paths().root / j["result"]["change_raster_ref"]).is_file()
    rev = client.post("/api/jobs", json={**body, "params": {"earlier_dataset_id": d2, "later_dataset_id": d1}}).json()
    assert rev["status"] == "failed" and "earlier" in rev["error_details"]
    assert client.post("/api/jobs", json={**body, "params": {"earlier_dataset_id": d1, "later_dataset_id": d1}}).status_code == 422
    assert client.post("/api/jobs", json={**body, "params": {"earlier_dataset_id": d1, "later_dataset_id": 9999}}).status_code == 404
    nd = client.post("/api/jobs", json={**body, "index_name": "ndwi"}).json()  # ndwi was processed too -> works
    assert nd["status"] == "completed"
    miss = client.post("/api/jobs", json={**body, "index_name": "ndbi"}).json()
    assert miss["status"] == "completed"


def test_change_job_without_processed_raster_fails(client, region, db):
    _scene(S1)
    _scene(S2, scale=0.6)
    client.post("/api/jobs", json={"job_type": "scene_processing", "region": "synthville",
                                   "params": {"scene_path": f"synthville/{S1}", "indices": ["ndvi"]}})
    client.post("/api/jobs", json={"job_type": "scene_processing", "region": "synthville",
                                   "params": {"scene_path": f"synthville/{S2}", "indices": ["ndvi"]}})
    ids = [d["id"] for d in client.get("/api/datasets").json()["items"]]
    j = client.post("/api/jobs", json={"job_type": "change_detection", "region": "synthville", "index_name": "ndwi",
                                       "params": {"earlier_dataset_id": min(ids), "later_dataset_id": max(ids)}}).json()
    assert j["status"] == "failed" and "Process the scene first" in j["error_details"]


def test_non_runnable_job_type_stays_queued(client, region):
    j = client.post("/api/jobs", json={"job_type": "regional_analysis", "region": "synthville"}).json()
    assert j["status"] == "queued"


def test_job_runs_off_the_event_loop_when_not_inline(client, region, monkeypatch):
    """With the default setting, submit() hands the work to the worker thread and returns immediately."""
    _scene()
    calls = []
    monkeypatch.setenv("JOBS_RUN_INLINE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(runner._executor, "submit", lambda fn, *a: calls.append((fn.__name__, a)))
    try:
        j = _job(client).json()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert j["status"] == "queued" and calls and calls[0][0] == "run_job"


# ---------- command-line mode (no database) ----------
def test_cli_process_change_and_errors(tmp_path, capsys):
    root = tmp_path / "data"
    raw = tmp_path / "raw"
    make_scene(raw, S1)
    make_scene(raw, S2, scale=0.6)
    bbox = ",".join(map(str, scene_bbox_wgs84()))
    common = ["--data-dir", str(root)]
    for n in (S1, S2):
        assert cli.main([*common, "process", "--scene-dir", str(raw / n), "--region", "x", "--bbox", bbox, "--indices", "ndvi"]) == 0
    tifs = sorted((root / "processed" / "indices" / "x").glob("*.tif"))
    assert len(tifs) == 2
    assert cli.main([*common, "change", "--region", "x", "--earlier", str(tifs[0]), "--later", str(tifs[1])]) == 0
    assert list((root / "processed" / "changes" / "x").glob("*.tif")) and list((root / "processed" / "summaries" / "x").glob("*_change.parquet"))
    assert cli.main([*common, "inspect", str(tifs[0])]) == 0
    assert cli.main([*common, "process", "--scene-dir", str(raw / "nope"), "--region", "x", "--bbox", bbox]) == 2
    assert "ERROR" in capsys.readouterr().err
