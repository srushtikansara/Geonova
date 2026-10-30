"""Experiment A (Pandas engine). Region statistics per city/year.

Equivalence rules shared with the Spark engine:
  * rows count only if valid is True AND the index is not NaN/null
  * SD is the sample SD (ddof=1); median is exact; output sorted by keys
"""
import pandas as pd

INDICES = ["ndvi", "ndwi", "ndbi"]
KEYS = ["city", "year"]


def region_stats(df):
    total = df.groupby(KEYS).size().rename("total_pixels")
    parts = [total]
    for idx in INDICES:
        ok = df[df["valid"] & df[idx].notna()]
        g = ok.groupby(KEYS)[idx]
        s = pd.DataFrame({
            f"{idx}_mean": g.mean(),
            f"{idx}_sd": g.std(ddof=1),
            f"{idx}_median": g.median(),
            f"{idx}_n": g.size(),
        })
        parts.append(s)
    out = pd.concat(parts, axis=1)
    for idx in INDICES:
        out[f"{idx}_coverage"] = out[f"{idx}_n"] / out["total_pixels"]
    return out.reset_index().sort_values(KEYS).reset_index(drop=True)
