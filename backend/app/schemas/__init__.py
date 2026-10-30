from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Health(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    time_utc: datetime


class FeatureStatus(BaseModel):
    available: bool
    note: str


class SystemInfo(BaseModel):
    app_name: str
    version: str
    environment: str
    python_version: str
    cors_origins: list[str]
    features: dict[str, FeatureStatus]


class Region(BaseModel):
    id: str
    name: str
    state: str
    country: str
    bbox: list[float] = Field(description="min_lon, min_lat, max_lon, max_lat (WGS84), approximate")
    notes: str = ""
    configured: bool = True
    analysed: bool = Field(False, description="True only when real analysis results exist")


class RegionList(BaseModel):
    items: list[Region]
    count: int
    note: str


class Unavailable(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    reason: str


IndexName = Literal["ndvi", "ndwi", "ndbi"]
DatasetStatus = Literal["registered", "processing", "processed", "failed"]


class RegionCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$", description="Unique slug, e.g. 'pune'")
    name: str = Field(min_length=1, max_length=128)
    state: str = ""
    country: str = ""
    description: str = ""
    bbox: list[float] = Field(min_length=4, max_length=4, description="min_lon, min_lat, max_lon, max_lat")

    @model_validator(mode="after")
    def _check_bbox(self):
        a, b, c, d = self.bbox
        if not (-180 <= a < c <= 180 and -90 <= b < d <= 90):
            raise ValueError("bbox must satisfy -180<=min_lon<max_lon<=180 and -90<=min_lat<max_lat<=90")
        return self


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=128)
    mission: str = Field(min_length=1, max_length=64)
    sensor: str = Field(min_length=1, max_length=64)
    acquisition_date: date
    region: str = Field(description="Region code")
    status: DatasetStatus = "registered"
    processing_baseline: str | None = Field(None, max_length=16)
    metadata: dict = Field(default_factory=dict)


class DatasetOut(BaseModel):
    id: int
    name: str
    source: str
    mission: str
    sensor: str
    acquisition_date: date
    region: str
    status: str
    processing_baseline: str | None = None
    metadata: dict = {}
    created_at: datetime


class DatasetList(BaseModel):
    items: list[DatasetOut] = []
    count: int = 0
    note: str


class AnalyticsSummary(BaseModel):
    available: bool
    regions_analysed: int = 0
    scenes_processed: int = 0
    reason: str | None = None


class TemporalSeries(BaseModel):
    available: bool
    region: str | None = None
    index: str
    points: list[dict] = []
    reason: str | None = None


class RegionalIndexSummary(BaseModel):
    region: str
    index: str
    observations: int
    first_date: date
    last_date: date
    latest_mean: float | None = None
    latest_min: float | None = None
    latest_max: float | None = None
    latest_std: float | None = None
    latest_valid_pixels: int
    latest_total_pixels: int | None = None
    latest_coverage: float | None = Field(None, description="valid / total pixels of the latest observation")
    change_first_to_last: float | None = Field(None, description="latest mean minus earliest mean (an index difference, not proof of land-cover change)")
    synthetic_fixture: bool = False


class RegionalSummaryList(BaseModel):
    available: bool
    items: list[RegionalIndexSummary] = []
    reason: str | None = None
    includes_synthetic: bool = False


_Date = date  # alias: some models below have a field called `date`


class LegendStop(BaseModel):
    value: float
    colour: str


class Legend(BaseModel):
    label: str
    caption: str
    stops: list[LegendStop] = []
    classes: list[dict] = []


class RasterLayer(BaseModel):
    id: str
    kind: Literal["index", "change"]
    index: str
    region: str | None = None
    date: _Date | None = Field(None, description="acquisition date (index layers)")
    earlier_date: _Date | None = None
    later_date: _Date | None = None
    dataset_id: int | None = None
    data_kind: str = "observation"
    bounds: list[list[float]] = Field(description="[[south, west], [north, east]] in EPSG:4326")
    legend: Legend


class RasterLayerList(BaseModel):
    items: list[RasterLayer] = []
    count: int = 0
    note: str


class ClassSummary(BaseModel):
    dataset_id: int
    region: str | None = None
    date: _Date
    data_kind: str = "observation"
    bounds: list[list[float]]
    valid_pixels: int
    classes: list[dict]
    rules: dict
    note: str


TIMING_SCOPE = ("Median wall-clock of read Parquet -> filter/group/aggregate/window -> write Parquet, per trial. "
                "Excludes data generation, framework initialisation and warm-up runs.")


class BenchmarkOut(BaseModel):
    """One framework's measured run. `engine/records/mean_s/sd_s/throughput/data` are aliases the frontend reads."""
    id: int
    benchmark_id: int | None = None
    framework: str
    engine: str
    workload: str
    data_kind: str
    data: str
    dataset_size_label: str | None = None
    row_count: int
    records: int
    valid_rows: int | None = None
    output_rows: int | None = None
    output_bytes: int | None = None
    duration_s: float | None = None
    mean_s: float | None = None
    median_s: float | None = None
    min_s: float | None = None
    max_s: float | None = None
    sd_s: float | None = None
    runs: int | None = None
    trial_durations: list[float] | None = None
    init_s: float | None = None
    peak_rss_mb: float | None = None
    throughput: float | None = None
    speedup: float | None = None
    mae: float | None = None
    max_abs_err: float | None = None
    within_tolerance: bool | None = None
    environment: dict = {}
    timing_scope: str = TIMING_SCOPE
    status: str
    error_details: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SuiteOut(BaseModel):
    id: int
    status: Literal["queued", "running", "completed", "failed"]
    workload: str
    data_kind: str
    requested_rows: int
    input_rows: int | None = None
    trials: int
    warmup: int
    seed: int
    config: dict = {}
    environment: dict = {}
    data_generation_s: float | None = None
    speedup: float | None = Field(None, description="median Pandas time / median PySpark time; >1 means PySpark was faster")
    comparison: dict | None = None
    error_details: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    run_ids: list[int] = []
    runs: list[BenchmarkOut] | None = None
    note: str = "SYNTHETIC benchmark data (not satellite observations). Local-mode Spark on one machine, not a cluster."


class BenchmarkList(BaseModel):
    items: list[BenchmarkOut] = []
    count: int = 0
    suites: list[SuiteOut] = []
    note: str


class BenchmarkRequest(BaseModel):
    rows: int = Field(100_000, ge=100, le=20_000_000)
    trials: int = Field(5, ge=1, le=30)
    warmup: int = Field(1, ge=0, le=5)
    seed: int = Field(42, ge=0, le=2**31 - 1)
    regions: int = Field(3, ge=1, le=200)
    spark_master: str = Field("local[*]", pattern=r"^local\[(\*|[1-9][0-9]?)\]$")
    shuffle_partitions: int | None = Field(None, ge=1, le=2000)
    spark_driver_memory: str = Field("2g", pattern=r"^[1-9][0-9]{0,2}[mg]$")
    spark_write: Literal["auto", "native", "collect"] = "auto"
    keep_artifacts: bool = False
    confirm: bool = Field(False, description="Must be true for runs of 1,000,000 rows or more")


class Preflight(BaseModel):
    rows: int
    estimated_peak_mb: float
    available_mb: float | None
    estimated_disk_mb: float
    memory_ok: bool
    requires_confirmation: bool
    spark: dict
    environment: dict
    note: str


JobStatus = Literal["queued", "running", "completed", "failed"]


class JobCreate(BaseModel):
    job_type: str = Field(default="regional_analysis", min_length=1, max_length=64)
    region: str | None = Field(None, description="Region code")
    dataset_id: int | None = None
    index_name: IndexName | None = None
    params: dict = Field(default_factory=dict, description="Job-type specific parameters")


class Job(BaseModel):
    id: str
    status: JobStatus
    kind: str
    created_utc: datetime
    region: str | None = None
    dataset_id: int | None = None
    index_name: str | None = None
    started_utc: datetime | None = None
    completed_utc: datetime | None = None
    error_details: str | None = None
    params: dict = {}
    result: dict = {}


class JobList(BaseModel):
    items: list[Job] = []
    count: int = 0
