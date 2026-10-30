"""Reflectance conversion, masking and spectral indices (NumPy)."""
import numpy as np

QUANT = 10000.0


def to_reflectance(dn, offset):
    """reflectance = (DN + offset) / 10000. DN == 0 is NoData -> NaN.

    The offset must be read from each product's metadata (it is -1000 from
    processing baseline 04.00, 25 Jan 2022, and 0 before). Never hard-code it.
    """
    dn = np.asarray(dn, dtype=np.float64)
    out = (dn + float(offset)) / QUANT
    out[dn == 0] = np.nan
    return out


def valid_mask(scl, valid_classes):
    return np.isin(np.asarray(scl), list(valid_classes))


def _norm_diff(a, b):
    """(a - b)/(a + b); NaN where the denominator is 0 or any input is NaN."""
    num = a - b
    den = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(den == 0, np.nan, num / den)
    return out


def ndvi(nir, red):
    return _norm_diff(nir, red)


def ndwi(green, nir):  # McFeeters (1996)
    return _norm_diff(green, nir)


def ndbi(swir, nir):
    return _norm_diff(swir, nir)


def block_mean_2x2(a):
    """Average 2x2 blocks (10 m -> 20 m), ignoring NaN. Crops odd edges."""
    h, w = a.shape
    h2, w2 = h // 2 * 2, w // 2 * 2
    b = a[:h2, :w2].reshape(h2 // 2, 2, w2 // 2, 2)
    with np.errstate(all="ignore"):
        return np.nanmean(b, axis=(1, 3))
