"""SYNTHETIC data. Used ONLY for testing and speed benchmarks. Never report
synthetic values as environmental findings."""
import numpy as np
import pandas as pd

from .tabulate import COLUMNS

CITIES = ["Ahmedabad", "Surat", "Pune"]


def synthetic_records(n, seed=0, nan_frac=0.02, invalid_frac=0.25):
    rng = np.random.default_rng(seed)
    city = rng.choice(CITIES, n)
    year = rng.choice([2021, 2022, 2023, 2024, 2025], n).astype(np.int32)
    month = rng.integers(1, 13, n).astype(np.int32)
    day = rng.integers(1, 28, n)
    date = [f"{y}-{m:02d}-{d:02d}" for y, m, d in zip(year, month, day)]
    df = pd.DataFrame({
        "city": city, "date": date, "year": year, "month": month,
        "row": rng.integers(0, 2000, n).astype(np.int32),
        "col": rng.integers(0, 2000, n).astype(np.int32),
        "ndvi": rng.normal(0.3, 0.2, n).clip(-1, 1),
        "ndwi": rng.normal(-0.2, 0.2, n).clip(-1, 1),
        "ndbi": rng.normal(0.05, 0.15, n).clip(-1, 1),
        "valid": rng.random(n) > invalid_frac,
    })
    for c in ("ndvi", "ndwi", "ndbi"):
        df.loc[rng.random(n) < nan_frac, c] = np.nan
    return df[COLUMNS]
