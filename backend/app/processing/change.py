"""Temporal change: delta = later_index - earlier_index, on a verified common grid."""
from datetime import date
from pathlib import Path

import numpy as np

from . import raster, stats
from .errors import GridError, InputError

MIN_OVERLAP = 0.5  # fraction of the earlier raster's valid pixels that must still be covered after alignment


def detect_change(earlier_path: Path, later_path: Path, *, align: bool = True,
                  threshold: float = stats.CHANGE_THRESHOLD) -> dict:
    """Returns {'delta': array, 'grid': Grid, 'summary': dict, 'aligned': bool, 'tags': dict}."""
    a, ga, ta = raster.read_geotiff(earlier_path)
    b, gb, tb = raster.read_geotiff(later_path)
    for t, label in ((ta, "earlier"), (tb, "later")):
        if "INDEX" not in t or "ACQUISITION_DATE" not in t:
            raise InputError(f"The {label} raster lacks GEONOVA metadata tags; produce it with this pipeline.")
    if ta["INDEX"] != tb["INDEX"]:
        raise InputError(f"Different indices cannot be compared ({ta['INDEX']} vs {tb['INDEX']}).")
    if ta.get("REGION") != tb.get("REGION"):
        raise InputError("The two observations belong to different regions.")
    if ta.get("DATA_KIND") != tb.get("DATA_KIND"):
        raise InputError("Cannot mix real observations with synthetic test fixtures.")
    d1, d2 = date.fromisoformat(ta["ACQUISITION_DATE"]), date.fromisoformat(tb["ACQUISITION_DATE"])
    if d1 >= d2:
        raise InputError("The earlier observation must be strictly before the later one.")

    aligned = False
    if not ga.same_as(gb):
        if not align:
            raise GridError("Rasters differ in CRS, transform or size and alignment was not allowed.")
        b, _ = raster.align(b, gb, ga)  # later -> earlier grid (bilinear, or average when downsampling)
        aligned = True
        valid_before = int(np.isfinite(a).sum())
        if valid_before == 0 or np.isfinite(a + b).sum() / valid_before < MIN_OVERLAP:
            raise GridError("The observations barely overlap after alignment.")
    delta = (b.astype(np.float64) - a.astype(np.float64)).astype(np.float32)
    valid = np.isfinite(delta)
    # total_pixel_count for change = pixels inside the earlier raster's region footprint (finite in either input)
    total = int((np.isfinite(a) | np.isfinite(b)).sum())
    summary = stats.summarize_change(delta, valid, total, threshold)
    summary.update(index=ta["INDEX"], region=ta.get("REGION"), earlier_date=d1.isoformat(), later_date=d2.isoformat(),
                   earlier_scene=ta.get("SOURCE_DATASET"), later_scene=tb.get("SOURCE_DATASET"),
                   data_kind=ta.get("DATA_KIND"), later_aligned_to_earlier=aligned,
                   resolution_m=ga.resolution)
    return {"delta": delta, "grid": ga, "summary": summary, "aligned": aligned, "tags": ta}
