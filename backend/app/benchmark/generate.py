"""Deterministic SYNTHETIC environmental dataset. These are NOT Sentinel-2 observations.

Schema: observation_id int64, region_id string, observation_date date32, ndvi/ndwi/ndbi float64 (nullable),
valid_pixel_count int32. Deliberate defects so the filter matters: ~2% nulls per index, ~1% out-of-range values,
~3% zero pixel counts. Written in chunks so memory stays bounded; same (rows, seed, regions) -> identical file.
"""
import json
import time
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

CHUNK = 1_000_000
START, DAYS = date(2021, 1, 1), 1826  # 2021-01-01 .. 2025-12-31
KNOWN = ["ahmedabad", "surat", "pune"]
SCHEMA = pa.schema([("observation_id", pa.int64()), ("region_id", pa.string()), ("observation_date", pa.date32()),
                    ("ndvi", pa.float64()), ("ndwi", pa.float64()), ("ndbi", pa.float64()),
                    ("valid_pixel_count", pa.int32())])
METADATA = {b"geonova_data_kind": b"synthetic_benchmark", b"note": b"synthetic benchmark data, not satellite observations"}


def region_names(n: int) -> list[str]:
    return [KNOWN[i] if i < len(KNOWN) else f"region_{i + 1:03d}" for i in range(n)]


def _chunk(rng: np.random.Generator, start_id: int, n: int, names: list[str]) -> pa.Table:
    reg = rng.integers(0, len(names), n)
    day = rng.integers(0, DAYS, n)
    year_idx = day // 365.25
    shift = (reg % 5) * 0.03
    ndvi = rng.normal(0.35 + shift - 0.01 * year_idx, 0.20, n).clip(-1, 1)
    ndwi = rng.normal(-0.25 - shift / 2, 0.20, n).clip(-1, 1)
    ndbi = rng.normal(0.05 + 0.01 * year_idx, 0.15, n).clip(-1, 1)
    arrs = {"ndvi": ndvi, "ndwi": ndwi, "ndbi": ndbi}
    for name, a in arrs.items():  # missing values (null) and out-of-range defects
        null = rng.random(n) < 0.02
        bad = rng.random(n) < 0.0033
        a[bad] = rng.choice([-1.5, 1.5], bad.sum())
        arrs[name] = np.ma.masked_array(a, mask=null)
    vpc = rng.integers(1, 10_001, n).astype(np.int32)
    vpc[rng.random(n) < 0.03] = 0
    days_since_epoch = (START - date(1970, 1, 1)).days + day
    cols = [pa.array(np.arange(start_id, start_id + n, dtype=np.int64)),
            pa.array(np.array(names, dtype=object)[reg], type=pa.string()),
            pa.array(days_since_epoch.astype(np.int32), type=pa.date32())]
    for name in ("ndvi", "ndwi", "ndbi"):
        m = arrs[name]
        cols.append(pa.array(m.data, mask=np.ma.getmaskarray(m), type=pa.float64()))
    cols.append(pa.array(vpc))
    return pa.Table.from_arrays(cols, schema=SCHEMA)


def generate_dataset(path: Path, rows: int, seed: int = 42, regions: int = 3) -> dict:
    """Write the Parquet file; returns {'rows', 'seconds', 'bytes', 'seed', 'regions', 'data_kind'}."""
    path.parent.mkdir(parents=True, exist_ok=True)
    names = region_names(regions)
    t0 = time.perf_counter()
    ss = np.random.SeedSequence([seed, rows, regions])
    writer = pq.ParquetWriter(path, SCHEMA.with_metadata(METADATA), compression="snappy")
    try:
        done = 0
        for k, child in enumerate(ss.spawn(-(-rows // CHUNK))):
            n = min(CHUNK, rows - done)
            writer.write_table(_chunk(np.random.default_rng(child), done, n, names))
            done += n
    finally:
        writer.close()
    return {"rows": rows, "seconds": time.perf_counter() - t0, "bytes": path.stat().st_size, "seed": seed,
            "regions": regions, "data_kind": "synthetic"}


if __name__ == "__main__":
    import sys
    print(json.dumps(generate_dataset(Path(sys.argv[1]), int(sys.argv[2]))))
