"""Benchmark configuration, validation and the memory estimate."""
import re
from dataclasses import asdict, dataclass

MAX_ROWS = 20_000_000
LARGE_ROWS = 1_000_000          # at or above this, the caller must confirm explicitly
MIN_ROWS = 100
_MASTER = re.compile(r"^local\[(\*|[1-9][0-9]?)\]$")

# Heuristic, calibrated against measured runs (see README "Memory estimate"). NOT a guarantee.
MB_BASE = 700.0          # interpreter + libraries + JVM start-up (per framework worker, run one at a time)
MB_PER_MILLION_ROWS = 420.0
SAFETY_FRACTION = 0.70   # refuse when the estimate exceeds this share of currently available RAM


class ConfigError(ValueError):
    """Invalid benchmark configuration (maps to HTTP 422)."""


@dataclass
class BenchmarkConfig:
    rows: int = 100_000
    trials: int = 5
    warmup: int = 1
    seed: int = 42
    regions: int = 3
    spark_master: str = "local[*]"
    shuffle_partitions: int | None = None   # default: number of local cores
    spark_driver_memory: str = "2g"
    spark_write: str = "auto"               # "auto" | "native" (Spark's Parquet writer) | "collect" (toPandas + pyarrow; labelled)
    keep_artifacts: bool = False            # keep the generated INPUT file (outputs are always kept)

    def validate(self) -> "BenchmarkConfig":
        if not isinstance(self.rows, int) or not (MIN_ROWS <= self.rows <= MAX_ROWS):
            raise ConfigError(f"rows must be an integer between {MIN_ROWS:,} and {MAX_ROWS:,}.")
        if not (1 <= self.trials <= 30):
            raise ConfigError("trials must be between 1 and 30.")
        if not (0 <= self.warmup <= 5):
            raise ConfigError("warmup must be between 0 and 5.")
        if not (1 <= self.regions <= 200):
            raise ConfigError("regions must be between 1 and 200.")
        if not _MASTER.match(self.spark_master):
            raise ConfigError("spark_master must be local[*] or local[N] (local mode only; no cluster).")
        if self.shuffle_partitions is not None and not (1 <= self.shuffle_partitions <= 2000):
            raise ConfigError("shuffle_partitions must be between 1 and 2000.")
        if not re.match(r"^[1-9][0-9]{0,2}[mg]$", self.spark_driver_memory):
            raise ConfigError("spark_driver_memory must look like 512m or 2g.")
        if self.spark_write not in ("auto", "native", "collect"):
            raise ConfigError("spark_write must be 'auto', 'native' or 'collect'.")
        return self

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_peak_mb(rows: int) -> float:
    """Approximate peak resident memory (MB) of ONE framework worker at a time."""
    return MB_BASE + MB_PER_MILLION_ROWS * rows / 1_000_000


def estimate_dataset_disk_mb(rows: int) -> float:
    return 40.0 * rows / 1_000_000 + 1.0   # compressed Parquet, ~40 MB per million rows (measured, approximate)


def check_memory(rows: int, available_mb: float) -> tuple[bool, float]:
    need = estimate_peak_mb(rows)
    return need <= SAFETY_FRACTION * available_mb, need
