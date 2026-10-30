"""End-to-end demo of the processing workflow through the HTTP API, using SYNTHETIC test rasters.

The scenes are generated fixtures, NOT Sentinel-2 observations. The server must run with
ALLOW_SYNTHETIC_PERSIST=true (otherwise it refuses to store them, by design). Do not use a database you
care about: the demo adds a 'synthville' region, two datasets, jobs and regional statistics, all
marked data_kind=synthetic_test_fixture (hidden by default in the dashboard).

    python scripts/demo_synthetic_workflow.py --api http://localhost:8000
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import rasterio  # noqa: E402

from app.processing.runner import data_paths  # noqa: E402
from app.tests.synthetic_scene import make_scene, scene_bbox_wgs84  # noqa: E402

S1, S2 = "S2X_SYNTH_20230115T050209", "S2X_SYNTH_20240115T050209"


def submit(c, body: dict, timeout: float = 120) -> dict:
    """POST a job and poll until it leaves queued/running (jobs run in a background worker)."""
    j = c.post("/jobs", json=body).json()
    end = time.time() + timeout
    while j.get("status") in ("queued", "running") and time.time() < end:
        time.sleep(1)
        j = c.get(f"/jobs/{j['id']}").json()
    return j


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    a = ap.parse_args()
    c = httpx.Client(base_url=f"{a.api}/api", timeout=120)
    paths = data_paths()
    raw = paths.raw / "synthville"
    make_scene(raw, S1)
    make_scene(raw, S2, scale=0.6)
    print("1. synthetic scenes written under", raw.name)
    r = c.post("/regions", json={"code": "synthville", "name": "Synthville (synthetic)", "bbox": scene_bbox_wgs84()})
    print("2. region:", r.status_code, "(409 = already exists)")
    ids = []
    for s in (S1, S2):
        j = submit(c, {"job_type": "scene_processing", "region": "synthville", "params": {"scene_path": f"synthville/{s}"}})
        print(f"3. scene job {s}: {j['status']} {j.get('error_details') or ''}")
        if j["status"] != "completed":
            return 1
        ids.append(j["result"]["dataset_id"])
        for k, v in j["result"]["indices"].items():
            with rasterio.open(paths.root / v["raster_ref"]) as ds:
                print(f"   {k}: crs={ds.crs} nodata={ds.nodata} size={ds.width}x{ds.height} dtype={ds.dtypes[0]}")
    j = submit(c, {"job_type": "change_detection", "region": "synthville", "index_name": "ndvi",
                   "params": {"earlier_dataset_id": ids[0], "later_dataset_id": ids[1], "threshold": 0.05}})
    print("4. change job:", j["status"], j.get("error_details") or j["result"].get("summary"))
    t = c.get("/analytics/temporal", params={"index": "ndvi", "region": "synthville", "include_synthetic": True}).json()
    print("5. temporal points via API:", len(t["points"]))
    return 0 if j["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
