"""Spectral indices on reflectance arrays (NaN = invalid).

Validity rules (documented, applied to every index):
  * any NaN/inf input  -> NaN
  * denominator <= 0   -> NaN   (covers division by zero and meaningless negative sums)
  * |result| > 1       -> NaN   (impossible for non-negative reflectance; flags bad data)
"""
import numpy as np

FORMULAS = {
    "ndvi": ("(B8 - B4) / (B8 + B4)", ("B08", "B04")),
    "ndwi": ("(B3 - B8) / (B3 + B8)", ("B03", "B08")),  # McFeeters (1996)
    "ndbi": ("(B11 - B8) / (B11 + B8)", ("B11", "B08")),
}
_LIMIT = 1.0 + 1e-6


def normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b) with the validity rules above. Returns float32."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    den = a + b
    ok = np.isfinite(a) & np.isfinite(b) & (den > 0)
    out = np.full(a.shape, np.nan, dtype=np.float64)
    np.divide(a - b, den, out=out, where=ok)
    out[~np.isfinite(out) | (np.abs(out) > _LIMIT)] = np.nan
    return out.astype(np.float32)


def ndvi(nir_b8, red_b4): return normalized_difference(nir_b8, red_b4)
def ndwi(green_b3, nir_b8): return normalized_difference(green_b3, nir_b8)
def ndbi(swir_b11, nir_b8): return normalized_difference(swir_b11, nir_b8)


def compute(name: str, bands: dict[str, np.ndarray]) -> np.ndarray:
    _, (first, second) = FORMULAS[name]
    return normalized_difference(bands[first], bands[second])
