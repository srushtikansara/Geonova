"""Offline tests of the Sentinel-2 window fetcher using SYNTHETIC local rasters as the 'remote' files.
They do NOT test the live Planetary Computer service."""
import importlib.util
import json
from pathlib import Path

import pytest
import rasterio

from app.processing import scene as scene_mod
from app.processing.paths import DataPaths
from app.processing.pipeline import Params, process_scene
from .synthetic_scene import make_scene, scene_bbox_wgs84

_spec = importlib.util.spec_from_file_location("fetch_s2", Path(__file__).resolve().parents[2] / "scripts" / "fetch_sentinel2.py")
fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch)


def _hrefs(src_dir: Path) -> dict:
    out = {}
    for p in src_dir.iterdir():
        for b in fetch.BANDS:
            if p.name.endswith(f"{b}_{fetch.BANDS[b]}m.tif"):
                out[b] = str(p)
    return out


@pytest.fixture()
def remote(tmp_path):
    d = make_scene(tmp_path / "remote", cloud_patch=False)
    return d, _hrefs(d)


def test_offset_from_baseline_is_never_guessed():
    assert fetch.boa_offset_from_baseline("05.10") == -1000
    assert fetch.boa_offset_from_baseline("04.00") == -1000
    assert fetch.boa_offset_from_baseline("03.01") == 0
    with pytest.raises(ValueError):
        fetch.boa_offset_from_baseline(None)


def test_region_bbox_known_and_unknown():
    assert fetch.region_bbox("pune") == [73.74, 18.45, 73.99, 18.65]
    with pytest.raises(SystemExit):
        fetch.region_bbox("atlantis")


def test_window_is_georeferenced_and_smaller_than_source(remote, tmp_path):
    d, hrefs = remote
    small = scene_bbox_wgs84(shrink_m=300.0)
    info = fetch.write_window(hrefs["B04"], small, tmp_path / "w.tif")
    with rasterio.open(hrefs["B04"]) as s, rasterio.open(tmp_path / "w.tif") as w:
        assert w.crs == s.crs and w.transform.a == s.transform.a and w.dtypes == s.dtypes and w.nodata == s.nodata
        assert w.width < s.width and w.height < s.height and info["width"] == w.width
        # pixel values equal the source at the same geographic place
        x, y = w.transform * (0.5, 0.5)
        assert w.read(1)[0, 0] == next(s.sample([(x, y)]))[0]


def test_window_outside_scene_is_refused(remote, tmp_path):
    with pytest.raises(Exception):
        fetch.write_window(remote[1]["B04"], [10.0, 10.0, 10.1, 10.1], tmp_path / "x.tif")


def test_fetched_folder_loads_and_processes(remote, tmp_path):
    d, hrefs = remote
    out = fetch.fetch_scene(hrefs, scene_bbox_wgs84(shrink_m=100.0), tmp_path / "raw" / "pune" / "ITEM1", "T43PGP_20230115T050209",
                            {"acquisition_date": "2023-01-15", "boa_add_offset": -1000})
    mf = json.loads((out / "scene.json").read_text())
    assert mf["data_kind"] == "observation" and "Planetary Computer" in mf["source"]
    info = scene_mod.load_scene(out)
    assert info.acquisition_date.isoformat() == "2023-01-15" and info.has_mask and info.offset_source == "scene.json"
    res = process_scene(out, "pune", scene_bbox_wgs84(shrink_m=150.0), DataPaths(tmp_path / "data").ensure(), Params())
    assert set(res.indices) == {"ndvi", "ndwi", "ndbi"} and res.indices["ndvi"]["stats"]["valid_pixel_count"] > 0


def test_missing_band_fails_clearly(remote, tmp_path):
    _, hrefs = remote
    hrefs.pop("B11")
    with pytest.raises(ValueError, match="B11"):
        fetch.fetch_scene(hrefs, scene_bbox_wgs84(), tmp_path / "o", "T43PGP_20230115T050209", {})
