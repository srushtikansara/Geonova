"""Command-line tool: works WITHOUT a database (files-only development mode).

  python -m app.processing.cli process --scene-dir data/raw/pune/S2B_... --region pune
  python -m app.processing.cli change  --region pune --index ndvi --earlier <tif> --later <tif>
  python -m app.processing.cli inspect <file.tif | file.parquet>

Nothing is persisted to PostgreSQL in this mode; results are the GeoTIFF/Parquet files plus the JSON printed here.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import rasterio

from app.core.config import get_settings
from .errors import ProcessingError
from .paths import DataPaths
from .pipeline import Params, process_scene, run_change

REGIONS = Path(__file__).resolve().parents[1] / "data" / "regions.json"


def _paths(a) -> DataPaths:
    root = Path(a.data_dir or get_settings().data_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    return DataPaths(root).ensure()


def _bbox(a) -> list[float]:
    if a.bbox:
        vals = [float(x) for x in a.bbox.split(",")]
        if len(vals) != 4:
            raise ProcessingError("--bbox needs min_lon,min_lat,max_lon,max_lat")
        return vals
    for r in json.loads(REGIONS.read_text(encoding="utf-8")):
        if r["id"] == a.region:
            return r["bbox"]
    raise ProcessingError(f"Unknown region '{a.region}'. Pass --bbox min_lon,min_lat,max_lon,max_lat.")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="geonova-process", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", help="Storage root (default: DATA_DIR setting)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("process", help="Compute NDVI/NDWI/NDBI for one scene")
    s1.add_argument("--scene-dir", required=True, type=Path)
    s1.add_argument("--region", required=True)
    s1.add_argument("--bbox", help="Override region box: min_lon,min_lat,max_lon,max_lat")
    s1.add_argument("--indices", default="ndvi,ndwi,ndbi")
    s1.add_argument("--resolution", type=int, default=20, choices=(10, 20))
    s1.add_argument("--scl-classes", default="4,5,6,7")
    s1.add_argument("--allow-missing-mask", action="store_true")
    s1.add_argument("--acquisition-date")
    s1.add_argument("--boa-add-offset", type=float)
    s1.add_argument("--data-kind", choices=("observation", "synthetic_test_fixture"))
    s1.add_argument("--source")
    s2 = sub.add_parser("change", help="later - earlier for one index")
    s2.add_argument("--region", required=True)
    s2.add_argument("--earlier", required=True, type=Path)
    s2.add_argument("--later", required=True, type=Path)
    s2.add_argument("--threshold", type=float, default=0.05)
    s2.add_argument("--no-align", action="store_true")
    s3 = sub.add_parser("inspect", help="Print metadata of a GeoTIFF or the head of a Parquet file")
    s3.add_argument("file", type=Path)
    a = p.parse_args(argv)
    try:
        if a.cmd == "process":
            params = Params(indices=tuple(a.indices.split(",")), target_resolution=a.resolution,
                            valid_scl_classes=tuple(int(x) for x in a.scl_classes.split(",")),
                            allow_missing_mask=a.allow_missing_mask,
                            acquisition_date=date.fromisoformat(a.acquisition_date) if a.acquisition_date else None,
                            boa_add_offset=a.boa_add_offset, data_kind=a.data_kind, source=a.source)
            res = process_scene(a.scene_dir, a.region, _bbox(a), _paths(a), params)
            print(json.dumps(res.to_dict(), indent=2, default=str))
        elif a.cmd == "change":
            paths = _paths(a)
            print(json.dumps(run_change(a.earlier, a.later, paths, region_code=a.region, align=not a.no_align,
                                        threshold=a.threshold), indent=2, default=str))
        else:
            if a.file.suffix.lower() == ".parquet":
                print(pd.read_parquet(a.file).T.to_string())
            else:
                with rasterio.open(a.file) as src:
                    print(json.dumps({"crs": src.crs.to_string(), "size": [src.width, src.height],
                                      "pixel_size": [src.transform.a, src.transform.e], "nodata": src.nodata,
                                      "dtype": src.dtypes[0], "tags": src.tags()}, indent=2))
    except (ProcessingError, ValueError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
