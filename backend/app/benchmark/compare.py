"""Numerical equivalence of the two engines' outputs."""
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

TABLES = {"annual_summary": ["region_id", "year"], "regional_summary": ["region_id"], "annual_change": ["region_id", "year"]}
EXACT = {"year", "obs_count", "valid_pixel_sum"}
RTOL, ATOL = 1e-9, 1e-12  # floating point: sums are accumulated in different orders by the two engines


def read_table(path: Path) -> pd.DataFrame:
    return pq.read_table(path).to_pandas(date_as_object=False)  # a directory of part files is read as one table


def compare_outputs(pandas_dir: Path, spark_dir: Path, rtol: float = RTOL, atol: float = ATOL) -> dict:
    cols, passed, errors = {}, True, []
    for name, keys in TABLES.items():
        a = read_table(pandas_dir / f"{name}.parquet").sort_values(keys).reset_index(drop=True)
        b = read_table(spark_dir / f"{name}.parquet").sort_values(keys).reset_index(drop=True)
        if list(a.columns) != list(b.columns):
            errors.append(f"{name}: different columns"); passed = False; continue
        if len(a) != len(b) or not a[keys].astype(str).equals(b[keys].astype(str)):
            errors.append(f"{name}: different rows/keys ({len(a)} vs {len(b)})"); passed = False; continue
        for c in a.columns:
            if c in keys:
                continue
            x, y = a[c].to_numpy(dtype="float64"), b[c].to_numpy(dtype="float64")
            nan_x, nan_y = np.isnan(x), np.isnan(y)
            ok = bool((nan_x == nan_y).all())
            both = ~(nan_x | nan_y)
            diff = np.abs(x[both] - y[both])
            if c in EXACT:
                ok = ok and bool((diff == 0).all())
            else:
                ok = ok and bool((diff <= atol + rtol * np.abs(y[both])).all())
            cols[f"{name}.{c}"] = {"mae": float(diff.mean()) if diff.size else 0.0,
                                   "max_abs_err": float(diff.max()) if diff.size else 0.0,
                                   "null_pattern_equal": bool((nan_x == nan_y).all()), "passed": ok,
                                   "rule": "exact" if c in EXACT else "tolerance"}
            passed &= ok
    mae = float(np.mean([v["mae"] for v in cols.values()])) if cols else None
    mx = max((v["max_abs_err"] for v in cols.values()), default=None)
    return {"passed": bool(passed and not errors), "mae": mae, "max_abs_err": mx, "rtol": rtol, "atol": atol,
            "columns": cols, "errors": errors,
            "rule": "counts, years and pixel sums must match exactly; floats within atol + rtol*|value|; null positions must match"}
