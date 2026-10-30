"""Build a multi-year series for one region: download one clear same-season scene per year, process each, and compare
consecutive years. Needs the API running (python -m uvicorn app.main:app --port 8000) and `pip install -r requirements-fetch.txt`.

    python scripts/build_timeseries.py --region ahmedabad --years 2021 2022 2023 2024 2025 --season 01-01 03-31

Using the same season every year avoids confusing seasonal vegetation cycles with real change. Scenes are real Sentinel-2
L2A windows (Planetary Computer). STATUS: the download path has not been run against the live service by the author;
the processing and API steps are covered by the test-suite on synthetic rasters.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402

import fetch_sentinel2 as fs  # noqa: E402


def submit(c: httpx.Client, body: dict, timeout: float = 600) -> dict:
    j = c.post("/jobs", json=body).json()
    end = time.time() + timeout
    while j.get("status") in ("queued", "running") and time.time() < end:
        time.sleep(2)
        j = c.get(f"/jobs/{j['id']}").json()
    return j


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", required=True)
    ap.add_argument("--years", type=int, nargs="+", required=True)
    ap.add_argument("--season", nargs=2, default=["01-01", "03-31"], metavar=("MM-DD", "MM-DD"), help="same window every year")
    ap.add_argument("--max-cloud", type=float, default=10.0)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--indices", nargs="+", default=["ndvi"], help="indices to compare between consecutive years")
    a = ap.parse_args()
    try:
        import planetary_computer  # noqa: F401
        import pystac_client  # noqa: F401
    except ImportError:
        print("ERROR: pip install -r requirements-fetch.txt")
        return 2
    from app.processing.runner import data_paths
    root = data_paths().root
    c = httpx.Client(base_url=f"{a.api}/api", timeout=120)
    datasets = []  # (year, dataset_id)
    for y in sorted(a.years):
        print(f"== {y}")
        got = fs.fetch_region_scenes(a.region, f"{y}-{a.season[0]}", f"{y}-{a.season[1]}", a.max_cloud, 1, root)
        if not got:
            print(f"   no usable scene for {y}; try --max-cloud 20 or a wider --season. Skipping this year.")
            continue
        j = submit(c, {"job_type": "scene_processing", "region": a.region, "params": {"scene_path": f"{a.region}/{got[0]['scene_id']}"}})
        print(f"   processing: {j['status']} {j.get('error_details') or ''}")
        if j["status"] == "completed":
            datasets.append((y, j["result"]["dataset_id"]))
    for (y0, d0), (y1, d1) in zip(datasets, datasets[1:]):
        for idx in a.indices:
            j = submit(c, {"job_type": "change_detection", "region": a.region, "index_name": idx,
                           "params": {"earlier_dataset_id": d0, "later_dataset_id": d1}})
            print(f"== change {idx} {y0}->{y1}: {j['status']} {j.get('error_details') or ''}")
    print(f"Done: {len(datasets)} year(s) processed. Open the Geospatial Explorer and choose {a.region}.")
    return 0 if datasets else 1


if __name__ == "__main__":
    raise SystemExit(main())
