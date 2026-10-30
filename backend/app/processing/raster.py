"""Raster I/O: region clipping, DN->reflectance, grid alignment, masks, GeoTIFF writing."""
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import rasterio
from rasterio import features
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.errors import WindowError
from rasterio.transform import Affine
from rasterio.warp import reproject, transform_geom
from rasterio.windows import Window, from_bounds

from .errors import GridError, InputError

OUT_NODATA = -9999.0


@dataclass
class Grid:
    crs: CRS
    transform: Affine
    height: int
    width: int

    @property
    def resolution(self) -> float:
        return abs(self.transform.a)

    def same_as(self, other: "Grid", tol: float = 1e-6) -> bool:
        return (self.crs == other.crs and self.height == other.height and self.width == other.width
                and all(abs(a - b) <= tol for a, b in zip(tuple(self.transform)[:6], tuple(other.transform)[:6])))


def bbox_polygon(bbox: list[float], n: int = 25) -> dict:
    """WGS84 box as a GeoJSON polygon with densified edges (a lon/lat box is curved in UTM)."""
    x0, y0, x1, y1 = bbox
    xs, ys = np.linspace(x0, x1, n), np.linspace(y0, y1, n)
    ring = ([(x, y0) for x in xs] + [(x1, y) for y in ys[1:]] + [(x, y1) for x in xs[::-1][1:]]
            + [(x0, y) for y in ys[::-1][1:]])
    return {"type": "Polygon", "coordinates": [ring]}


def polygon_in_crs(poly: dict, crs: CRS) -> dict:
    return transform_geom("EPSG:4326", crs, poly)


def _bounds(geom: dict):
    pts = np.array(geom["coordinates"][0])
    return pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()


def read_clipped(path, geom_crs: dict) -> tuple[np.ndarray, Grid, dict]:
    """Read band 1 over the window covering `geom_crs` (polygon already in the raster CRS)."""
    with rasterio.open(path) as src:
        full = Window(0, 0, src.width, src.height)
        want = from_bounds(*_bounds(geom_crs), transform=src.transform)
        want = want.round_offsets(op="floor").round_lengths(op="ceil")
        try:
            win = want.intersection(full)
        except WindowError:
            raise InputError("The region does not overlap this raster.")
        if win.width < 1 or win.height < 1:
            raise InputError("The region does not overlap this raster.")
        data = src.read(1, window=win)
        grid = Grid(src.crs, src.window_transform(win), int(win.height), int(win.width))
        info = {"truncated_by_raster_edge": bool(
            (win.col_off, win.row_off, win.width, win.height) != (want.col_off, want.row_off, want.width, want.height)),
            "nodata": src.nodata, "dtype": src.dtypes[0]}
    return data, grid, info


def to_reflectance(dn: np.ndarray, offset: float, quantification: float, nodata=None) -> np.ndarray:
    """reflectance = (DN + offset) / quantification. DN == 0 (and the file's nodata value) -> NaN.
    Negative results are kept (not clipped); the index code treats non-positive sums as invalid."""
    dn = np.asarray(dn)
    refl = (dn.astype(np.float32) + np.float32(offset)) / np.float32(quantification)
    bad = dn == 0
    if nodata is not None:
        bad |= dn == nodata
    refl[bad] = np.nan
    return refl


def align(arr: np.ndarray, src: Grid, dst: Grid, *, categorical: bool = False) -> tuple[np.ndarray, str]:
    """Resample onto `dst`. Returns (array, method). Identical grids are returned untouched.
    Downsampling (10->20 m): GDAL 'average' over valid sub-pixels. Upsampling: 'bilinear'. Categorical: 'nearest'."""
    if src.same_as(dst):
        return arr, "none"
    if categorical:
        method, rs = "nearest", Resampling.nearest
    elif src.resolution < dst.resolution - 1e-6:
        method, rs = "average", Resampling.average
    else:
        method, rs = "bilinear", Resampling.bilinear
    out = np.full((dst.height, dst.width), 0 if categorical else np.nan, dtype=arr.dtype if categorical else np.float32)
    reproject(source=arr, destination=out, src_transform=src.transform, src_crs=src.crs,
              dst_transform=dst.transform, dst_crs=dst.crs, resampling=rs,
              src_nodata=None if categorical else np.nan, dst_nodata=None if categorical else np.nan)
    return out, method


def region_mask(geom_crs: dict, grid: Grid) -> np.ndarray:
    """True where the pixel CENTRE lies inside the region polygon (all_touched=False)."""
    return features.geometry_mask([geom_crs], out_shape=(grid.height, grid.width), transform=grid.transform,
                                  invert=True, all_touched=False)


def scl_valid(scl: np.ndarray, valid_classes) -> np.ndarray:
    return np.isin(scl, list(valid_classes))


def write_geotiff(path, array: np.ndarray, grid: Grid, tags: dict[str, str], nodata: float = OUT_NODATA) -> None:
    """float32 single-band GeoTIFF; NaN is stored as `nodata`. CRS and transform come from `grid`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.where(np.isfinite(array), array, nodata).astype(np.float32)
    with rasterio.open(path, "w", driver="GTiff", height=grid.height, width=grid.width, count=1, dtype="float32",
                       crs=grid.crs, transform=grid.transform, nodata=nodata, compress="deflate", predictor=3) as dst:
        dst.write(data, 1)
        dst.update_tags(**{k: str(v) for k, v in tags.items()})


def read_geotiff(path) -> tuple[np.ndarray, Grid, dict[str, str]]:
    """Read an index/change GeoTIFF written by this package; nodata -> NaN."""
    try:
        with rasterio.open(path) as src:
            arr = src.read(1).astype(np.float32)
            nd = src.nodata
            if nd is not None:
                arr[arr == nd] = np.nan
            arr[~np.isfinite(arr)] = np.nan
            return arr, Grid(src.crs, src.transform, src.height, src.width), src.tags()
    except rasterio.errors.RasterioIOError:
        raise InputError("Raster file is missing or unreadable.")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
