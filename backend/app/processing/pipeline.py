"""Scene processing and change detection, writing GeoTIFF + Parquet outputs."""
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import change as change_mod, indices as ix, raster, scene as scene_mod, stats
from .errors import GridError, InputError, ProcessingError
from .paths import DataPaths

DEFAULT_VALID_SCL = (4, 5, 6, 7)  # vegetation, not vegetated, water, unclassified
SCL_NOTE = ("SCL classes kept as valid: {c}. Excluded: 0 no-data, 1 saturated/defective, 2 dark area, 3 cloud shadow, "
            "8/9 cloud (medium/high probability), 10 thin cirrus, 11 snow/ice (unless listed).")
NOT_LANDCOVER = "Index values and their changes are spectral signals, not validated land-cover classes."


@dataclass
class Params:
    indices: tuple[str, ...] = ("ndvi", "ndwi", "ndbi")
    target_resolution: int = 20  # metres; 20 = analysis grid decision D1, 10 = upsample B11
    valid_scl_classes: tuple[int, ...] = DEFAULT_VALID_SCL
    allow_missing_mask: bool = False
    # overrides for scene metadata
    acquisition_date: date | None = None
    boa_add_offset: float | None = None
    quantification: float | None = None
    data_kind: str | None = None
    source: str | None = None

    def validate(self):
        bad = [i for i in self.indices if i not in ix.FORMULAS]
        if bad or not self.indices:
            raise InputError(f"Unknown or empty index list: {bad or 'none'}.")
        if self.target_resolution not in (10, 20):
            raise InputError("target_resolution must be 10 or 20.")

    def as_dict(self) -> dict:
        return {"indices": list(self.indices), "target_resolution_m": self.target_resolution,
                "valid_scl_classes": list(self.valid_scl_classes), "allow_missing_mask": self.allow_missing_mask}


@dataclass
class SceneResult:
    scene_id: str
    region: str
    acquisition_date: str
    data_kind: str
    source: str
    parameters: dict
    grid: dict
    limitations: list[str]
    indices: dict[str, dict] = field(default_factory=dict)  # name -> {raster_ref, stats, formula, bands}
    summary_ref: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def process_scene(directory: Path, region_code: str, bbox: list[float], paths: DataPaths, params: Params | None = None) -> SceneResult:
    params = params or Params()
    params.validate()
    info = scene_mod.load_scene(directory, acquisition_date=params.acquisition_date, boa_add_offset=params.boa_add_offset,
                                quantification=params.quantification, data_kind=params.data_kind, source=params.source)
    facts = scene_mod.validate_band_files(info)
    limitations = list(info.warnings)
    if info.has_mask is False and not params.allow_missing_mask:
        raise InputError("No SCL cloud mask found. Add the SCL file, or explicitly allow_missing_mask=True "
                         "(results will then include cloud-contaminated pixels).")
    res = params.target_resolution
    needed = {b for name in params.indices for b in ix.FORMULAS[name][1]}

    # Region polygon in the raster CRS, and the target grid from a reference band at the target resolution.
    from rasterio.crs import CRS
    crs = CRS.from_string(next(iter(facts.values()))["crs"])
    poly = raster.polygon_in_crs(raster.bbox_polygon(bbox), crs)
    ref_band = "B08" if res == 10 else "B11"
    if abs(facts[ref_band]["res_m"] - res) / res > 0.01:
        # e.g. only 20 m B08 exists but 10 m was requested
        raise InputError(f"Cannot build a {res} m grid: {ref_band} is {facts[ref_band]['res_m']:g} m in the supplied files.")
    _, grid, ginfo = raster.read_clipped(info.bands[ref_band], poly)
    rmask = raster.region_mask(poly, grid)
    total = int(rmask.sum())
    if total == 0:
        raise InputError("The region contains no pixel centres on this grid (region too small or outside the scene).")
    if ginfo["truncated_by_raster_edge"]:
        limitations.append("The region extends beyond the scene edge; statistics cover only the part inside the scene.")

    refl, methods = {}, {}
    for b in sorted(needed):
        dn, g, binfo = raster.read_clipped(info.bands[b], poly)
        arr = raster.to_reflectance(dn, info.boa_add_offset, info.quantification, binfo["nodata"])
        refl[b], methods[b] = raster.align(arr, g, grid)

    if info.has_mask:
        scl, g, _ = raster.read_clipped(info.bands["SCL"], poly)
        scl, _ = raster.align(scl, g, grid, categorical=True)
        mask_ok = raster.scl_valid(scl, params.valid_scl_classes)
        limitations.append(SCL_NOTE.format(c=list(params.valid_scl_classes)))
    else:
        mask_ok = np.ones(grid.height, dtype=bool)[:, None] & np.ones(grid.width, dtype=bool)[None, :]
        limitations.append("NO cloud/shadow mask was applied (allow_missing_mask=True); cloudy pixels are included.")

    resampling = {b: m for b, m in methods.items() if m != "none"}
    if resampling:
        limitations.append("Resampled to the common grid: " + ", ".join(f"{b}={m}" for b, m in resampling.items())
                           + ". 'average' = mean of valid sub-pixels (10->20 m); 'bilinear' = upsampling (20->10 m).")
    limitations.append(f"Reflectance = (DN + {info.boa_add_offset:g}) / {info.quantification:g}; offset source: {info.offset_source}. DN 0 = nodata.")
    limitations.append("Region box is approximate; a pixel counts if its centre is inside the (reprojected) polygon.")
    limitations.append(NOT_LANDCOVER)
    if info.data_kind != "observation":
        limitations.insert(0, "SYNTHETIC TEST FIXTURE: not a satellite observation.")

    out = SceneResult(scene_id=info.scene_id, region=region_code, acquisition_date=info.acquisition_date.isoformat(),
                      data_kind=info.data_kind, source=info.source, parameters=params.as_dict(),
                      grid={"crs": grid.crs.to_string(), "transform": list(tuple(grid.transform)[:6]),
                            "height": grid.height, "width": grid.width, "resolution_m": grid.resolution},
                      limitations=limitations,
                      metadata={"offset_source": info.offset_source, "boa_add_offset": info.boa_add_offset,
                                "quantification": info.quantification, "band_files": {b: p.name for b, p in info.bands.items()},
                                "band_facts": facts, "notes": info.notes, "cloud_mask_applied": info.has_mask})
    rows = []
    for name in params.indices:
        formula, bands_used = ix.FORMULAS[name]
        arr = ix.compute(name, refl)
        valid = rmask & mask_ok & np.isfinite(arr)
        arr_out = np.where(valid, arr, np.nan)
        st = stats.summarize(arr, valid, total)
        tif = paths.indices / region_code / f"{info.scene_id}_{name}_{res}m.tif"
        raster.write_geotiff(tif, arr_out, grid, {
            "INDEX": name, "FORMULA": formula, "INPUT_BANDS": ",".join(bands_used), "REGION": region_code,
            "ACQUISITION_DATE": info.acquisition_date.isoformat(), "PROCESSING_DATE": raster.now_iso(),
            "RESOLUTION_M": grid.resolution, "SOURCE_DATASET": info.scene_id, "SOURCE": info.source,
            "DATA_KIND": info.data_kind, "REFLECTANCE_OFFSET": info.boa_add_offset, "CLOUD_MASK_APPLIED": info.has_mask,
            "VALID_SCL_CLASSES": ",".join(map(str, params.valid_scl_classes)) if info.has_mask else "none",
            "NODATA_VALUE": raster.OUT_NODATA, "NOTE": NOT_LANDCOVER})
        out.indices[name] = {"raster_ref": paths.rel(tif), "stats": st, "formula": formula, "input_bands": list(bands_used)}
        rows.append({"region": region_code, "scene_id": info.scene_id, "acquisition_date": info.acquisition_date.isoformat(),
                     "index": name, "resolution_m": grid.resolution, "data_kind": info.data_kind, "source": info.source,
                     "mean": st["mean"], "min": st["min"], "max": st["max"], "std": st["std"],
                     "valid_pixel_count": st["valid_pixel_count"], "total_pixel_count": st["total_pixel_count"],
                     "coverage": st["coverage"], "cloud_mask_applied": info.has_mask,
                     "parameters": json.dumps(params.as_dict()), "processing_utc": raster.now_iso()})
    pq = paths.summaries / region_code / f"{info.scene_id}_summary.parquet"
    pq.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(pq, index=False)
    out.summary_ref = paths.rel(pq)
    return out


def run_change(earlier: Path, later: Path, paths: DataPaths, *, region_code: str, align: bool = True,
               threshold: float = stats.CHANGE_THRESHOLD) -> dict:
    res = change_mod.detect_change(earlier, later, align=align, threshold=threshold)
    s = res["summary"]
    if s["region"] != region_code:
        raise InputError("The observations do not belong to the requested region.")
    stem = f"{s['index']}_{s['earlier_date']}_to_{s['later_date']}"
    tif = paths.changes / region_code / f"{stem}.tif"
    raster.write_geotiff(tif, res["delta"], res["grid"], {
        "INDEX": s["index"], "KIND": "change = later - earlier", "REGION": region_code,
        "EARLIER_DATE": s["earlier_date"], "LATER_DATE": s["later_date"], "EARLIER_SCENE": s["earlier_scene"],
        "LATER_SCENE": s["later_scene"], "THRESHOLD": s["threshold"], "DATA_KIND": s["data_kind"],
        "PROCESSING_DATE": raster.now_iso(), "NOTE": NOT_LANDCOVER, "NODATA_VALUE": raster.OUT_NODATA})
    pq = paths.summaries / region_code / f"{stem}_change.parquet"
    pq.parent.mkdir(parents=True, exist_ok=True)
    row = {**s, "interpretation": "spectral-index change; not a validated land-cover transition",
           "processing_utc": raster.now_iso()}
    pd.DataFrame([row]).to_parquet(pq, index=False)
    return {"summary": s, "change_raster_ref": paths.rel(tif), "summary_ref": paths.rel(pq)}
