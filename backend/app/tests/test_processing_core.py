"""Tests with SYNTHETIC fixtures (see synthetic_scene.py). They verify the code, not real imagery."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from app.processing import change as change_mod, indices as ix, raster, scene as scene_mod, stats
from app.processing.errors import GridError, InputError
from app.processing.paths import DataPaths
from app.processing.pipeline import Params, process_scene, run_change
from .synthetic_scene import REFL, expected, make_scene, scene_bbox_wgs84

BBOX = scene_bbox_wgs84()


@pytest.fixture()
def paths(tmp_path):
    return DataPaths(tmp_path / "data").ensure()


# ---------- indices: known values, division by zero, nodata ----------
def test_index_known_values():
    nir, red, green, swir = np.array([0.5]), np.array([0.1]), np.array([0.3]), np.array([0.4])
    assert ix.ndvi(nir, red)[0] == pytest.approx(0.4 / 0.6)
    assert ix.ndwi(green, nir)[0] == pytest.approx(-0.2 / 0.8)
    assert ix.ndbi(swir, nir)[0] == pytest.approx(-0.1 / 0.9)


def test_index_division_by_zero_nan_inf_and_range():
    a = np.array([0.0, np.nan, np.inf, 0.3, -0.5, 0.2], dtype=np.float32)
    b = np.array([0.0, 0.2, 0.2, np.nan, 0.1, -0.1], dtype=np.float32)
    out = ix.normalized_difference(a, b)
    assert np.isnan(out).all()  # zero denominator, NaN, inf, non-positive sums are all invalid
    assert not np.isinf(out).any()
    assert ix.normalized_difference(np.array([1.0]), np.array([0.0]))[0] == pytest.approx(1.0)


def test_nodata_preserved_through_reflectance():
    dn = np.array([[0, 1000, 11000]], dtype=np.uint16)
    r = raster.to_reflectance(dn, -1000, 10000)
    assert np.isnan(r[0, 0]) and r[0, 1] == 0 and r[0, 2] == pytest.approx(1.0)
    r2 = raster.to_reflectance(np.array([[500, 2000]], dtype=np.uint16), 0, 10000, nodata=500)
    assert np.isnan(r2[0, 0]) and r2[0, 1] == pytest.approx(0.2)


# ---------- scene discovery, metadata, validation ----------
def test_missing_directory_and_bands(tmp_path):
    with pytest.raises(InputError, match="does not exist"):
        scene_mod.load_scene(tmp_path / "nope")
    d = make_scene(tmp_path, omit=("B11",))
    with pytest.raises(InputError, match="B11"):
        scene_mod.load_scene(d)


def test_offset_and_data_kind_are_never_guessed(tmp_path):
    d = make_scene(tmp_path, manifest=False)
    with pytest.raises(InputError, match="offset"):
        scene_mod.load_scene(d, acquisition_date=pd.Timestamp("2023-01-15").date())
    with pytest.raises(InputError, match="data_kind"):
        scene_mod.load_scene(d, acquisition_date=pd.Timestamp("2023-01-15").date(), boa_add_offset=-1000)
    info = scene_mod.load_scene(d, boa_add_offset=-1000, data_kind="synthetic_test_fixture")
    assert info.acquisition_date.isoformat() == "2023-01-15"  # parsed from the folder name
    assert info.offset_source == "argument"


def test_mtd_offset_parsing_uses_metadata(tmp_path):
    # Minimal SYNTHETIC XML shaped like MTD_MSIL2A.xml (verify the real file's layout on a real product).
    d = make_scene(tmp_path, manifest=False)
    (d / "MTD_MSIL2A.xml").write_text(
        '<n1:Level-2A_User_Product xmlns:n1="x"><BOA_QUANTIFICATION_VALUE unit="none">10000</BOA_QUANTIFICATION_VALUE>'
        '<BOA_ADD_OFFSET_VALUES_LIST><BOA_ADD_OFFSET band_id="0">-1000</BOA_ADD_OFFSET>'
        '<BOA_ADD_OFFSET band_id="1">-1000</BOA_ADD_OFFSET></BOA_ADD_OFFSET_VALUES_LIST></n1:Level-2A_User_Product>')
    info = scene_mod.load_scene(d)
    assert info.boa_add_offset == -1000 and info.offset_source == "MTD_MSIL2A.xml" and info.data_kind == "observation"


def test_invalid_files_crs_and_resolution(tmp_path):
    d = make_scene(tmp_path)
    (d / "B03_10m.tif").write_bytes(b"not a raster")
    info = scene_mod.load_scene(d)
    with pytest.raises(InputError, match="cannot be opened"):
        scene_mod.validate_band_files(info)
    d2 = make_scene(tmp_path, name="S2X_SYNTH_20230210T050209")
    with rasterio.open(d2 / "B04_10m.tif", "w", driver="GTiff", height=4, width=4, count=1, dtype="uint16",
                       transform=from_origin(0, 0, 10, 10)) as dst:  # no CRS
        dst.write(np.ones((4, 4), dtype=np.uint16), 1)
    with pytest.raises(InputError, match="no CRS"):
        scene_mod.validate_band_files(scene_mod.load_scene(d2))
    d3 = make_scene(tmp_path, name="S2X_SYNTH_20230301T050209")
    with rasterio.open(d3 / "B08_10m.tif", "w", driver="GTiff", height=4, width=4, count=1, dtype="uint16",
                       crs="EPSG:32643", transform=from_origin(0, 0, 60, 60)) as dst:
        dst.write(np.ones((4, 4), dtype=np.uint16), 1)
    with pytest.raises(InputError, match="pixel size"):
        scene_mod.validate_band_files(scene_mod.load_scene(d3))


def test_path_traversal_refused(paths):
    for bad in ("../x", "/etc/passwd", ""):
        with pytest.raises(InputError):
            paths.resolve_ref(bad, paths.raw)


# ---------- alignment, CRS/transform preservation ----------
def test_alignment_10m_to_20m_is_exact_block_average():
    arr = np.arange(16, dtype=np.float32).reshape(4, 4)
    src = raster.Grid(CRS.from_epsg(32643), from_origin(0, 80, 10, 10), 4, 4)
    dst = raster.Grid(CRS.from_epsg(32643), from_origin(0, 80, 20, 20), 2, 2)
    out, method = raster.align(arr, src, dst)
    assert method == "average"
    assert out[0, 0] == pytest.approx((0 + 1 + 4 + 5) / 4) and out[1, 1] == pytest.approx((10 + 11 + 14 + 15) / 4)
    same, m2 = raster.align(arr, src, src)
    assert m2 == "none" and same is arr


def test_alignment_ignores_nodata_subpixels():
    arr = np.array([[1, np.nan], [3, 5]], dtype=np.float32)
    src = raster.Grid(CRS.from_epsg(32643), from_origin(0, 20, 10, 10), 2, 2)
    dst = raster.Grid(CRS.from_epsg(32643), from_origin(0, 20, 20, 20), 1, 1)
    out, _ = raster.align(arr, src, dst)
    assert out[0, 0] == pytest.approx(3.0)  # mean of the three valid sub-pixels


# ---------- full scene pipeline ----------
def test_process_scene_values_masks_and_outputs(paths, tmp_path):
    d = make_scene(tmp_path / "raw")
    res = process_scene(d, "pune", BBOX, paths, Params())
    assert res.data_kind == "synthetic_test_fixture" and res.acquisition_date == "2023-01-15"
    assert res.grid["resolution_m"] == 20 and res.grid["crs"] == "EPSG:32643"
    assert any("SYNTHETIC" in s for s in res.limitations)
    for name in ("ndvi", "ndwi", "ndbi"):
        tif = paths.root / res.indices[name]["raster_ref"]
        with rasterio.open(tif) as src:
            assert src.crs == CRS.from_epsg(32643) and src.nodata == raster.OUT_NODATA and src.dtypes[0] == "float32"
            assert src.transform.a == 20 and src.transform.e == -20  # square 20 m pixels, north-up
            tags = src.tags()
            assert tags["INDEX"] == name and tags["DATA_KIND"] == "synthetic_test_fixture" and tags["SOURCE_DATASET"] == d.name
            assert tags["INPUT_BANDS"] and tags["RESOLUTION_M"] == "20.0" and tags["ACQUISITION_DATE"] == "2023-01-15"
            arr = src.read(1)
        valid = arr != raster.OUT_NODATA
        vals = {round(float(v), 4) for v in arr[valid]}
        assert vals == {round(expected(name, 0), 4), round(expected(name, 1), 4)}  # known values, both halves
        st = res.indices[name]["stats"]
        assert 0 < st["valid_pixel_count"] < st["total_pixel_count"]  # cloud patch + region edge removed pixels
    # The 10x10-pixel cloud patch (scene x < X0+200 m, y > Y0-200 m) is masked: no valid pixel has its centre there.
    from .synthetic_scene import X0, Y0
    with rasterio.open(paths.root / res.indices["ndvi"]["raster_ref"]) as src:
        arr, tr = src.read(1), src.transform
        rows, cols = np.indices(arr.shape)
        xs, ys = tr.c + (cols + 0.5) * tr.a, tr.f + (rows + 0.5) * tr.e
        in_cloud = (xs < X0 + 200) & (ys > Y0 - 200)
        assert in_cloud.sum() > 0
        assert (arr[in_cloud] == raster.OUT_NODATA).all()
        assert (arr[~in_cloud & (arr != raster.OUT_NODATA)] != raster.OUT_NODATA).all()
    df = pd.read_parquet(paths.root / res.summary_ref)
    assert set(df["index"]) == {"ndvi", "ndwi", "ndbi"} and (df["data_kind"] == "synthetic_test_fixture").all()
    assert df["cloud_mask_applied"].all()


def test_regional_stats_exact_for_ndvi(paths, tmp_path):
    d = make_scene(tmp_path / "raw", cloud_patch=False)
    res = process_scene(d, "pune", BBOX, paths, Params(indices=("ndvi",)))
    st = res.indices["ndvi"]["stats"]
    lo, hi = sorted((expected("ndvi", 0), expected("ndvi", 1)))
    assert st["min"] == pytest.approx(lo, abs=1e-5) and st["max"] == pytest.approx(hi, abs=1e-5)
    assert lo < st["mean"] < hi and st["std"] > 0
    assert st["coverage"] == pytest.approx(1.0)  # no cloud: every in-region pixel is valid


def test_nodata_pixels_are_excluded(paths, tmp_path):
    clean = process_scene(make_scene(tmp_path / "a", cloud_patch=False), "pune", BBOX, paths, Params(indices=("ndvi",)))
    holes = process_scene(make_scene(tmp_path / "b", name="S2X_SYNTH_20230125T050209", cloud_patch=False, nodata_patch=True),
                          "pune", BBOX, paths, Params(indices=("ndvi",)))
    # 2x2 whole 20 m pixels lose B04 entirely (every 10 m sub-pixel is DN 0), so exactly four valid pixels fewer
    assert holes.indices["ndvi"]["stats"]["valid_pixel_count"] == clean.indices["ndvi"]["stats"]["valid_pixel_count"] - 4


def test_missing_mask_is_never_silently_cloud_free(paths, tmp_path):
    d = make_scene(tmp_path / "raw", with_scl=False)
    with pytest.raises(InputError, match="cloud mask"):
        process_scene(d, "pune", BBOX, paths, Params())
    res = process_scene(d, "pune", BBOX, paths, Params(allow_missing_mask=True, indices=("ndvi",)))
    assert any("NO cloud" in s for s in res.limitations) and res.metadata["cloud_mask_applied"] is False


def test_region_outside_scene_and_bad_params(paths, tmp_path):
    d = make_scene(tmp_path / "raw")
    with pytest.raises(InputError, match="overlap"):
        process_scene(d, "x", [72.4, 22.9, 72.5, 23.0], paths, Params())  # Ahmedabad box, scene is near Pune
    with pytest.raises(InputError):
        process_scene(d, "pune", BBOX, paths, Params(indices=("evi",)))
    with pytest.raises(InputError):
        process_scene(d, "pune", BBOX, paths, Params(target_resolution=30))


def test_10m_grid_upsamples_b11_and_is_documented(paths, tmp_path):
    d = make_scene(tmp_path / "raw", cloud_patch=False)
    res = process_scene(d, "pune", BBOX, paths, Params(indices=("ndbi",), target_resolution=10))
    assert res.grid["resolution_m"] == 10
    assert any("bilinear" in s for s in res.limitations)


# ---------- change detection ----------
def _two_dates(paths, tmp_path, scale=1.0, **kw):
    a = process_scene(make_scene(tmp_path / "e", name="S2X_SYNTH_20230115T050209", cloud_patch=False), "pune", BBOX, paths, Params(indices=("ndvi",)))
    b = process_scene(make_scene(tmp_path / "l", name="S2X_SYNTH_20240115T050209", cloud_patch=False, scale=scale, **kw), "pune", BBOX, paths, Params(indices=("ndvi",)))
    return a, b


def test_change_zero_when_identical(paths, tmp_path):
    a, b = _two_dates(paths, tmp_path)
    r = run_change(paths.root / a.indices["ndvi"]["raster_ref"], paths.root / b.indices["ndvi"]["raster_ref"], paths, region_code="pune")
    s = r["summary"]
    assert s["mean"] == pytest.approx(0.0, abs=1e-6) and s["prop_near_zero"] == pytest.approx(1.0)
    assert s["prop_positive"] == 0 and s["prop_negative"] == 0 and s["later_aligned_to_earlier"] is False
    with rasterio.open(paths.root / r["change_raster_ref"]) as src:
        assert src.crs == CRS.from_epsg(32643)
    df = pd.read_parquet(paths.root / r["summary_ref"])
    assert df.loc[0, "interpretation"].startswith("spectral-index change") and df.loc[0, "earlier_date"] == "2023-01-15"


def test_change_known_difference_and_proportions(paths, tmp_path):
    a, b = _two_dates(paths, tmp_path, scale=0.5)  # NIR halves -> NDVI falls
    r = run_change(paths.root / a.indices["ndvi"]["raster_ref"], paths.root / b.indices["ndvi"]["raster_ref"], paths, region_code="pune")
    s = r["summary"]
    def ndvi(nir, red): return (nir - red) / (nir + red)
    d0 = ndvi(0.4 * .5, .05) - ndvi(0.4, .05)
    d1 = ndvi(0.2 * .5, .15) - ndvi(0.2, .15)
    assert s["min"] == pytest.approx(min(d0, d1), abs=1e-4) and s["max"] == pytest.approx(max(d0, d1), abs=1e-4)
    assert s["prop_negative"] == pytest.approx(1.0) and s["prop_positive"] == 0
    assert s["valid_pixel_count"] > 0 and s["std"] is not None


def test_change_threshold_proportions_unit():
    d = np.array([0.2, -0.2, 0.01, -0.01, 0.05, np.nan])
    s = stats.summarize_change(d, np.isfinite(d), 6, threshold=0.05)
    assert (s["prop_positive"], s["prop_negative"], s["prop_near_zero"]) == (0.2, 0.2, 0.6)
    assert s["valid_pixel_count"] == 5 and s["total_pixel_count"] == 6


def test_change_rejects_bad_pairs(paths, tmp_path):
    a, b = _two_dates(paths, tmp_path)
    ea, lb = paths.root / a.indices["ndvi"]["raster_ref"], paths.root / b.indices["ndvi"]["raster_ref"]
    with pytest.raises(InputError, match="earlier"):
        run_change(lb, ea, paths, region_code="pune")  # reversed order
    with pytest.raises(InputError, match="region"):
        run_change(ea, lb, paths, region_code="surat")
    with pytest.raises(InputError, match="missing"):
        run_change(ea, paths.root / "nope.tif", paths, region_code="pune")
    other = process_scene(make_scene(tmp_path / "o", name="S2X_SYNTH_20240301T050209", cloud_patch=False), "pune", BBOX, paths, Params(indices=("ndwi",)))
    with pytest.raises(InputError, match="Different indices"):
        run_change(ea, paths.root / other.indices["ndwi"]["raster_ref"], paths, region_code="pune")
    real = process_scene(make_scene(tmp_path / "r", name="S2X_SYNTH_20240401T050209", cloud_patch=False, data_kind="observation"), "pune", BBOX, paths, Params(indices=("ndvi",)))
    with pytest.raises(InputError, match="synthetic"):
        run_change(ea, paths.root / real.indices["ndvi"]["raster_ref"], paths, region_code="pune")


def test_incompatible_grid_is_aligned_or_refused(paths, tmp_path):
    a = process_scene(make_scene(tmp_path / "e", name="S2X_SYNTH_20230115T050209", cloud_patch=False), "pune", BBOX, paths, Params(indices=("ndvi",)))
    # later scene on a grid shifted by 10 m (half a pixel): same CRS, different transform
    b = process_scene(make_scene(tmp_path / "l", name="S2X_SYNTH_20240115T050209", cloud_patch=False, x0=378010.0, y0=2049990.0),
                      "pune", BBOX, paths, Params(indices=("ndvi",)))
    ea, lb = paths.root / a.indices["ndvi"]["raster_ref"], paths.root / b.indices["ndvi"]["raster_ref"]
    ga = raster.read_geotiff(ea)[1]
    gb = raster.read_geotiff(lb)[1]
    if ga.same_as(gb):
        pytest.skip("grids happened to coincide")
    with pytest.raises(GridError):
        change_mod.detect_change(ea, lb, align=False)
    r = run_change(ea, lb, paths, region_code="pune")
    assert r["summary"]["later_aligned_to_earlier"] is True and r["summary"]["valid_pixel_count"] > 0


def test_no_overlap_after_alignment_fails(paths, tmp_path):
    a = process_scene(make_scene(tmp_path / "e", name="S2X_SYNTH_20230115T050209", cloud_patch=False), "pune", BBOX, paths, Params(indices=("ndvi",)))
    far = tmp_path / "far.tif"
    arr, g, tags = raster.read_geotiff(paths.root / a.indices["ndvi"]["raster_ref"])
    g2 = raster.Grid(g.crs, from_origin(g.transform.c + 50_000, g.transform.f, 20, 20), g.height, g.width)
    tags = {**tags, "ACQUISITION_DATE": "2024-01-15"}
    raster.write_geotiff(far, arr, g2, tags)
    with pytest.raises(GridError, match="overlap"):
        change_mod.detect_change(paths.root / a.indices["ndvi"]["raster_ref"], far)


def test_summary_statistics_known_values():
    v = np.array([1.0, 2.0, 3.0, 4.0, np.nan, 100.0], dtype=np.float32)
    valid = np.array([True, True, True, True, True, False])  # NaN and the masked 100 are excluded
    s = stats.summarize(v, valid, total_pixels=6)
    assert s["valid_pixel_count"] == 4 and s["total_pixel_count"] == 6 and s["coverage"] == pytest.approx(4 / 6)
    assert s["mean"] == 2.5 and s["min"] == 1.0 and s["max"] == 4.0
    assert s["std"] == pytest.approx(1.2909944, abs=1e-6)  # sample SD (ddof=1)
    empty = stats.summarize(v, np.zeros(6, dtype=bool), 6)
    assert empty["valid_pixel_count"] == 0 and empty["mean"] is None and empty["std"] is None
