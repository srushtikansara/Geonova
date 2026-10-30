"""Summary statistics over valid pixels only."""
import numpy as np

CHANGE_THRESHOLD = 0.05  # |delta| <= this is "near zero". A documented, adjustable convention, NOT a calibrated value.


def _f(x):
    return None if x is None or not np.isfinite(x) else float(x)


def summarize(values: np.ndarray, valid: np.ndarray, total_pixels: int) -> dict:
    """`valid` selects the pixels that count; NaN values are excluded even if valid is True."""
    v = values[valid & np.isfinite(values)].astype(np.float64)
    n = int(v.size)
    base = {"valid_pixel_count": n, "total_pixel_count": int(total_pixels),
            "coverage": (n / total_pixels) if total_pixels else None}
    if n == 0:
        return {**base, "mean": None, "min": None, "max": None, "std": None}
    return {**base, "mean": float(v.mean()), "min": float(v.min()), "max": float(v.max()),
            "std": float(v.std(ddof=1)) if n > 1 else None}


def summarize_change(delta: np.ndarray, valid: np.ndarray, total_pixels: int, threshold: float = CHANGE_THRESHOLD) -> dict:
    if threshold < 0:
        raise ValueError("threshold must be >= 0")
    s = summarize(delta, valid, total_pixels)
    v = delta[valid & np.isfinite(delta)].astype(np.float64)
    n = v.size
    if n:
        s.update(prop_positive=float((v > threshold).sum() / n), prop_negative=float((v < -threshold).sum() / n),
                 prop_near_zero=float((np.abs(v) <= threshold).sum() / n))
    else:
        s.update(prop_positive=None, prop_negative=None, prop_near_zero=None)
    s["threshold"] = float(threshold)
    return s
