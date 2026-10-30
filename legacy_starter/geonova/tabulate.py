"""Turn per-scene index arrays into a flat record table (the Pandas/Spark input)."""
import numpy as np
import pandas as pd

COLUMNS = ["city", "date", "year", "month", "row", "col", "ndvi", "ndwi", "ndbi", "valid"]


def scene_to_frame(city, date, ndvi, ndwi, ndbi, valid):
    h, w = ndvi.shape
    rr, cc = np.indices((h, w))
    d = pd.Timestamp(date)
    df = pd.DataFrame({
        "city": city,
        "date": d.strftime("%Y-%m-%d"),
        "year": d.year,
        "month": d.month,
        "row": rr.ravel().astype(np.int32),
        "col": cc.ravel().astype(np.int32),
        "ndvi": ndvi.ravel(),
        "ndwi": ndwi.ravel(),
        "ndbi": ndbi.ravel(),
        "valid": valid.ravel(),
    })
    return df[COLUMNS]
