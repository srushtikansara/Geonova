"""Experiment D: numerical consistency between two result tables."""
import numpy as np
import pandas as pd


def compare(a, b, abs_tol=1e-9, rel_tol=1e-7):
    keys = ["city", "year"]
    a = a.sort_values(keys).reset_index(drop=True)
    b = b.sort_values(keys).reset_index(drop=True)
    if not a[keys].equals(b[keys]):
        return {"keys_match": False}
    num = [c for c in a.columns if c not in keys]
    rows = []
    for c in num:
        x = a[c].to_numpy(dtype=float)
        y = b[c].to_numpy(dtype=float)
        d = np.abs(x - y)
        ok = d <= abs_tol + rel_tol * np.abs(y)
        rows.append({"column": c, "mae": float(np.nanmean(d)), "max_abs_err": float(np.nanmax(d)),
                     "all_within_tol": bool(np.all(ok | (np.isnan(x) & np.isnan(y))))})
    rep = pd.DataFrame(rows)
    return {"keys_match": True, "table": rep, "pass": bool(rep["all_within_tol"].all())}
