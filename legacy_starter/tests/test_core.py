import os, sys
import numpy as np
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geonova import indices as ix, analysis_pandas as ap, analysis_spark as asp, compare
from geonova.synth import synthetic_records


def test_offset_and_nodata():
    dn = np.array([0, 1000, 2000, 11000])
    r = ix.to_reflectance(dn, -1000)
    assert np.isnan(r[0]) and r[1] == 0.0 and r[2] == 0.1 and r[3] == 1.0
    assert ix.to_reflectance(np.array([2000]), 0)[0] == 0.2


def test_indices_known_values():
    nir, red = np.array([0.5]), np.array([0.1])
    assert ix.ndvi(nir, red)[0] == pytest.approx(0.4 / 0.6)
    assert ix.ndwi(np.array([0.3]), np.array([0.1]))[0] == pytest.approx(0.5)
    assert ix.ndbi(np.array([0.4]), np.array([0.2]))[0] == pytest.approx(1 / 3)
    assert np.isnan(ix.ndvi(np.array([0.0]), np.array([0.0]))[0])


def test_block_mean():
    a = np.arange(16, dtype=float).reshape(4, 4)
    assert ix.block_mean_2x2(a).shape == (2, 2)
    assert ix.block_mean_2x2(a)[0, 0] == pytest.approx((0 + 1 + 4 + 5) / 4)


def test_scl_mask():
    m = ix.valid_mask(np.array([3, 4, 6, 9]), [4, 5, 6, 7])
    assert m.tolist() == [False, True, True, False]


def test_pandas_matches_manual():
    df = synthetic_records(5000, seed=3)
    out = ap.region_stats(df)
    c, y = out.iloc[0]["city"], out.iloc[0]["year"]
    sub = df[(df.city == c) & (df.year == y) & df.valid & df.ndvi.notna()]
    assert out.iloc[0]["ndvi_mean"] == pytest.approx(sub.ndvi.mean())
    assert out.iloc[0]["ndvi_n"] == len(sub)


def test_spark_equals_pandas():
    df = synthetic_records(50_000, seed=5)
    A = ap.region_stats(df)
    spark = asp.get_spark("local[2]")
    B = asp.region_stats(spark, df)
    rep = compare.compare(A, B)
    assert rep["keys_match"], "keys differ"
    assert rep["pass"], rep["table"]
