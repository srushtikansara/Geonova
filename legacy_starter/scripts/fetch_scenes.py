"""Fetch Sentinel-2 L2A windows for each city from Microsoft Planetary Computer
(public STAC, no account needed) and write per-scene index tables to Parquet.

NOT TESTED against the live service from the development sandbox (no network
access there). Run it on your laptop; if it errors, send me the full message.
Offset handling: read from the asset's raster metadata; fall back to the
processing baseline rule (>= 04.00 -> -1000). Always check the printed offset.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
import planetary_computer as pc
import rasterio
import yaml
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geonova import indices as ix  # noqa: E402
from geonova.tabulate import scene_to_frame  # noqa: E402

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"


def offset_for(item, asset_key):
    rb = item.assets[asset_key].extra_fields.get("raster:bands")
    if rb and "offset" in rb[0]:
        return float(rb[0]["offset"])
    base = item.properties.get("s2:processing_baseline", "00.00")
    return -1000.0 if float(base) >= 4.0 else 0.0


def read_band(item, key, bbox_ll, out_shape=None, resampling=Resampling.average):
    href = item.assets[key].href
    with rasterio.open(href) as src:
        b = transform_bounds("EPSG:4326", src.crs, *bbox_ll)
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        return src.read(1, window=win, out_shape=out_shape, resampling=resampling,
                        boundless=False)


def process_item(item, city, bbox, valid_classes):
    scl = read_band(item, "SCL", bbox, resampling=Resampling.nearest)
    shape = scl.shape
    g = read_band(item, "B03", bbox, shape)
    r = read_band(item, "B04", bbox, shape)
    n = read_band(item, "B08", bbox, shape)
    s = read_band(item, "B11", bbox, shape)
    off = offset_for(item, "B04")
    print(f"  {item.id} baseline={item.properties.get('s2:processing_baseline')} offset={off}")
    G, R, N, S = (ix.to_reflectance(a, off) for a in (g, r, n, s))
    valid = ix.valid_mask(scl, valid_classes)
    return scene_to_frame(city, item.datetime.date(), ix.ndvi(N, R), ix.ndwi(G, N), ix.ndbi(S, N), valid)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--out", default="data/records.parquet")
    p.add_argument("--max-scenes", type=int, default=None, help="limit per city (for a quick trial)")
    a = p.parse_args()
    cfg = yaml.safe_load(open(a.config))
    cat = Client.open(STAC, modifier=pc.sign_inplace)
    frames = []
    for city, bbox in cfg["cities"].items():
        y = cfg["year"]
        s = cat.search(collections=["sentinel-2-l2a"], bbox=bbox, datetime=f"{y}-01-01/{y}-12-31",
                       query={"eo:cloud_cover": {"lt": cfg["max_cloud_cover"]}})
        items = list(s.items())
        if a.max_scenes:
            items = items[: a.max_scenes]
        print(f"{city}: {len(items)} scenes")
        for it in items:
            try:
                frames.append(process_item(it, city, bbox, cfg["valid_scl_classes"]))
            except Exception as e:  # keep going, but never hide it
                print(f"  SKIPPED {it.id}: {e!r}")
    pd.concat(frames, ignore_index=True).to_parquet(a.out)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
