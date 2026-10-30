"""Turn index / change / class rasters into colour-coded PNG overlays for the map (no extra dependencies).

Colours are a presentation choice, not data: the numeric rasters (GeoTIFF) remain the result. Every scale below is
sent to the frontend as the legend, so the picture and its legend always agree.
"""
import struct
import zlib
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.warp import Resampling, calculate_default_transform, reproject

from .raster import OUT_NODATA

MAX_WIDTH = 1024

# value -> colour stops (hex). Linear interpolation between stops; values outside the range are clamped.
SCALES: dict[str, dict] = {
    "ndvi": {"label": "NDVI (vegetation)", "stops": [(-0.2, "#8c6d46"), (0.0, "#e6d9b0"), (0.2, "#d9e08a"), (0.4, "#7bbf4a"),
                                                       (0.6, "#2e8b2e"), (0.8, "#0b4d1c")],
             "caption": "Brown/sand: bare or built-up; light green: sparse plants; dark green: dense vegetation"},
    "ndwi": {"label": "NDWI (open water)", "stops": [(-0.5, "#d8c9a3"), (-0.2, "#f2ecd9"), (0.0, "#bfe3f0"), (0.25, "#4aa3d6"),
                                                       (0.5, "#08306b")],
             "caption": "Sand: dry land; light blue: moisture/shallow water; dark blue: open water"},
    "ndbi": {"label": "NDBI (built-up)", "stops": [(-0.5, "#2e8b57"), (-0.2, "#bcd9a8"), (0.0, "#f0e6c8"), (0.2, "#f4a261"),
                                                       (0.4, "#c0392b")],
             "caption": "Green: vegetated; cream: neutral; orange/red: built-up or bare surfaces"},
}
# difference (later - earlier) scales: decrease -> warm, no change -> white, increase -> cool/green
CHANGE_SCALES: dict[str, dict] = {
    "ndvi": {"label": "NDVI change (later - earlier)", "stops": [(-0.4, "#b2182b"), (-0.1, "#f4a582"), (0.0, "#f7f7f7"),
                                                                    (0.1, "#a6d96a"), (0.4, "#1a7a1a")],
             "caption": "Red: vegetation index decreased; white: little change; green: increased"},
    "ndwi": {"label": "NDWI change (later - earlier)", "stops": [(-0.4, "#b35806"), (-0.1, "#fdb863"), (0.0, "#f7f7f7"),
                                                                    (0.1, "#92c5de"), (0.4, "#08519c")],
             "caption": "Orange: water index decreased; white: little change; blue: increased"},
    "ndbi": {"label": "NDBI change (later - earlier)", "stops": [(-0.4, "#1a7a1a"), (-0.1, "#a6d96a"), (0.0, "#f7f7f7"),
                                                                    (0.1, "#f4a582"), (0.4, "#b2182b")],
             "caption": "Green: built-up index decreased; white: little change; red: increased"},
}
# threshold rules for the indicative land-cover layer (conventions, NOT validated)
CLASS_RULES = {"water_ndwi_gt": 0.0, "vegetation_ndvi_ge": 0.3, "built_ndbi_gt": 0.0, "built_ndvi_lt": 0.2}
CLASSES = [(1, "water", "Water", "#2b7bba"), (2, "vegetation", "Vegetation", "#2e7d32"),
           (3, "built", "Built-up / bare surface", "#d73027"), (4, "other", "Other", "#e0d3b8")]
CLASS_NOTE = ("Indicative classes from simple index thresholds applied in this order: water if NDWI > 0; vegetation if NDVI >= 0.3; "
              "built-up if NDBI > 0 and NDVI < 0.2; otherwise other. These are conventions, not a validated land-cover map.")


def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def colourise(arr: np.ndarray, stops: list[tuple[float, str]], nodata=OUT_NODATA) -> np.ndarray:
    """float array -> RGBA uint8; nodata/NaN pixels are fully transparent."""
    xs = [s[0] for s in stops]
    cols = np.array([_rgb(s[1]) for s in stops], dtype=float)
    valid = np.isfinite(arr) & (arr != nodata)
    out = np.zeros(arr.shape + (4,), dtype=np.uint8)
    v = np.where(valid, arr, xs[0])
    for c in range(3):
        out[..., c] = np.interp(v, xs, cols[:, c]).round().astype(np.uint8)
    out[..., 3] = np.where(valid, 255, 0)
    return out


def classify(ndvi: np.ndarray, ndwi: np.ndarray, ndbi: np.ndarray, nodata=OUT_NODATA) -> np.ndarray:
    """uint8 class codes (0 = no data). Pixels missing any of the three indices stay 0."""
    ok = np.isfinite(ndvi) & np.isfinite(ndwi) & np.isfinite(ndbi) & (ndvi != nodata) & (ndwi != nodata) & (ndbi != nodata)
    r = CLASS_RULES
    out = np.full(ndvi.shape, 4, dtype=np.uint8)
    built = (ndbi > r["built_ndbi_gt"]) & (ndvi < r["built_ndvi_lt"])
    out[built] = 3
    out[ndvi >= r["vegetation_ndvi_ge"]] = 2
    out[ndwi > r["water_ndwi_gt"]] = 1
    out[~ok] = 0
    return out


def class_rgba(codes: np.ndarray) -> np.ndarray:
    out = np.zeros(codes.shape + (4,), dtype=np.uint8)
    for code, _k, _l, hexc in CLASSES:
        m = codes == code
        out[m, :3] = _rgb(hexc)
        out[m, 3] = 255
    return out


def class_fractions(codes: np.ndarray) -> dict:
    valid = int((codes > 0).sum())
    res = {"valid_pixels": valid}
    for code, key, _l, _h in CLASSES:
        n = int((codes == code).sum())
        res[key] = {"pixels": n, "fraction": (n / valid) if valid else None}
    return res


def read_band(path: Path) -> tuple[np.ndarray, rasterio.Affine, CRS]:
    with rasterio.open(path) as s:
        return s.read(1).astype("float64"), s.transform, s.crs


def to_wgs84(arr: np.ndarray, transform, crs, *, fill, resampling=Resampling.nearest, dtype="float32"):
    """Reproject to a north-up EPSG:4326 grid (<= MAX_WIDTH wide). Returns (array, [[south, west], [north, east]])."""
    h, w = arr.shape
    bounds = rasterio.transform.array_bounds(h, w, transform)
    dst_t, dw, dh = calculate_default_transform(crs, "EPSG:4326", w, h, *bounds)
    if dw > MAX_WIDTH:
        target_h = max(1, round(dh * MAX_WIDTH / dw))
        dst_t, dw, dh = calculate_default_transform(crs, "EPSG:4326", w, h, *bounds, dst_width=MAX_WIDTH, dst_height=target_h)
    dst = np.full((dh, dw), fill, dtype=dtype)
    reproject(arr.astype(dtype), dst, src_transform=transform, src_crs=crs, dst_transform=dst_t, dst_crs="EPSG:4326",
              src_nodata=fill, dst_nodata=fill, resampling=resampling)
    west, north = dst_t * (0, 0)
    east, south = dst_t * (dw, dh)
    return dst, [[south, west], [north, east]]


def png_bytes(rgba: np.ndarray) -> bytes:
    """Minimal PNG encoder for an (H, W, 4) uint8 array."""
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


@lru_cache(maxsize=64)
def _index_png(path: str, mtime: float, kind: str, index: str) -> tuple[bytes, tuple]:
    arr, t, crs = read_band(Path(path))
    arr = np.where(arr == OUT_NODATA, np.nan, arr)
    out, bounds = to_wgs84(arr, t, crs, fill=np.nan)
    scale = (CHANGE_SCALES if kind == "change" else SCALES)[index]
    return png_bytes(colourise(out, scale["stops"])), tuple(map(tuple, bounds))


def index_png(path: Path, kind: str, index: str) -> tuple[bytes, list]:
    png, b = _index_png(str(path), path.stat().st_mtime, kind, index)
    return png, [list(x) for x in b]


@lru_cache(maxsize=64)
def _class_png(paths: tuple, mtimes: tuple) -> tuple[bytes, tuple, str]:
    import json
    (a, t, crs), (b, _, _), (c, _, _) = (read_band(Path(p)) for p in paths)  # ndvi, ndwi, ndbi on one grid
    codes = classify(a, b, c)
    out, bounds = to_wgs84(codes, t, crs, fill=0, resampling=Resampling.nearest, dtype="uint8")
    return png_bytes(class_rgba(out)), tuple(map(tuple, bounds)), json.dumps(class_fractions(codes))


def class_png(ndvi: Path, ndwi: Path, ndbi: Path) -> tuple[bytes, list, dict]:
    import json
    ps = (str(ndvi), str(ndwi), str(ndbi))
    png, b, frac = _class_png(ps, tuple(Path(p).stat().st_mtime for p in ps))
    return png, [list(x) for x in b], json.loads(frac)