"""The benchmark workload, Pandas implementation. Must stay logically identical to workload_spark.py.

Logical workload (both engines):
  1. valid := valid_pixel_count > 0 AND ndvi, ndwi, ndbi all non-null AND each within [-1, 1]
  2. year := year(observation_date)
  3. annual_summary   : group (region_id, year) -> obs_count, valid_pixel_sum, mean_ndvi/ndwi/ndbi, std_ndvi (sample),
                        min_ndvi, max_ndvi, weighted_mean_ndvi = sum(ndvi*vpc)/sum(vpc)
  4. regional_summary : group region_id over ALL valid rows (not a mean of annual means) -> same measures
  5. annual_change    : per region, mean_* minus previous year's mean_*, only when the previous row is exactly year-1
  6. write the three tables to Parquet, each sorted by its keys
Timing scope (both engines): read input Parquet -> steps 1-5 -> write outputs. Dataset generation is excluded.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

COLS = ["observation_id", "region_id", "observation_date", "ndvi", "ndwi", "ndbi", "valid_pixel_count"]
INDICES = ["ndvi", "ndwi", "ndbi"]


def run(input_path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pq.read_table(input_path, columns=COLS).to_pandas(date_as_object=False)
    ok = df["valid_pixel_count"] > 0
    for c in INDICES:
        ok &= df[c].between(-1.0, 1.0)  # NaN (from null) -> False
    v = df.loc[ok].copy()
    v["year"] = v["observation_date"].dt.year.astype("int32")
    v["w_ndvi"] = v["ndvi"] * v["valid_pixel_count"]

    def agg(keys):
        g = v.groupby(keys, sort=True)
        out = g.agg(obs_count=("observation_id", "size"), valid_pixel_sum=("valid_pixel_count", "sum"),
                    mean_ndvi=("ndvi", "mean"), mean_ndwi=("ndwi", "mean"), mean_ndbi=("ndbi", "mean"),
                    std_ndvi=("ndvi", "std"), min_ndvi=("ndvi", "min"), max_ndvi=("ndvi", "max"),
                    w_sum=("w_ndvi", "sum")).reset_index()
        out["weighted_mean_ndvi"] = out["w_sum"] / out["valid_pixel_sum"]
        out["obs_count"] = out["obs_count"].astype("int64")
        out["valid_pixel_sum"] = out["valid_pixel_sum"].astype("int64")
        return out.drop(columns="w_sum")

    annual = agg(["region_id", "year"])
    regional = agg(["region_id"])
    prev = annual.groupby("region_id")[["year", *[f"mean_{c}" for c in INDICES]]].shift(1)
    consecutive = (annual["year"] - prev["year"]) == 1
    change = annual[["region_id", "year"]].copy()
    for c in INDICES:
        change[f"delta_mean_{c}"] = np.where(consecutive, annual[f"mean_{c}"] - prev[f"mean_{c}"], np.nan)

    annual.to_parquet(out_dir / "annual_summary.parquet", index=False)
    regional.to_parquet(out_dir / "regional_summary.parquet", index=False)
    change.to_parquet(out_dir / "annual_change.parquet", index=False)
    return {}
