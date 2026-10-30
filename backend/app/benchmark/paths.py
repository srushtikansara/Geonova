from pathlib import Path

from app.core.config import get_settings


def data_root() -> Path:
    root = Path(get_settings().data_dir)
    return root if root.is_absolute() else Path(__file__).resolve().parents[2] / root


def bench_root() -> Path:
    """Configurable benchmark directory: <DATA_DIR>/benchmarks (git-ignored)."""
    return data_root() / "benchmarks"
