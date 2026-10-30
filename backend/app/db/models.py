"""ORM models. Rasters (GeoTIFF) and tables (Parquet) live on disk; the DB stores references."""
import uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (BigInteger, CheckConstraint, Date, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

INDEX_NAMES = ("ndvi", "ndwi", "ndbi")
DATASET_STATUSES = ("registered", "processing", "processed", "failed")
JOB_STATUSES = ("queued", "running", "completed", "failed")
BENCH_STATUSES = ("running", "completed", "failed")
FRAMEWORKS = ("pandas", "spark")


def _in(col: str, values) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now(), nullable=False)


class Region(TimestampMixin, Base):
    __tablename__ = "regions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    country: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    # Study-area polygon in WGS84; GeoAlchemy2 adds a GiST spatial index.
    geom = mapped_column(Geometry("POLYGON", srid=4326, spatial_index=True), nullable=False)

    datasets: Mapped[list["Dataset"]] = relationship(back_populates="region", cascade="all, delete-orphan",
                                                      passive_deletes=True)
    __table_args__ = (
        CheckConstraint("min_lon < max_lon AND min_lat < max_lat", name="bbox_ordered"),
        CheckConstraint("min_lon >= -180 AND max_lon <= 180 AND min_lat >= -90 AND max_lat <= 90", name="bbox_range"),
    )


class Dataset(TimestampMixin, Base):
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. "Copernicus Data Space"
    mission: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "Sentinel-2"
    sensor: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "MSI L2A"
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="registered", nullable=False)
    processing_baseline: Mapped[str | None] = mapped_column(String(16))
    extra: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    region: Mapped[Region] = relationship(back_populates="datasets")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="dataset")
    __table_args__ = (
        CheckConstraint(_in("status", DATASET_STATUSES), name="status_valid"),
        UniqueConstraint("region_id", "name", name="uq_datasets_region_name"),
        Index("ix_datasets_region_date", "region_id", "acquisition_date"),
    )


class AnalysisJob(TimestampMixin, Base):
    __tablename__ = "analysis_jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id", ondelete="SET NULL"))
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"))
    index_name: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_details: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False, server_default="{}")
    result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False, server_default="{}")

    region: Mapped[Region | None] = relationship()
    dataset: Mapped[Dataset | None] = relationship()
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="status_valid"),
        CheckConstraint(f"index_name IS NULL OR {_in('index_name', INDEX_NAMES)}", name="index_valid"),
        CheckConstraint("completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at", name="times_ordered"),
        CheckConstraint("status <> 'failed' OR error_details IS NOT NULL", name="failed_has_error"),
        Index("ix_analysis_jobs_status_created", "status", "created_at"),
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)  # raster | table | figure | log
    file_format: Mapped[str] = mapped_column(String(16), nullable=False)  # geotiff | parquet | png | csv
    storage_ref: Mapped[str] = mapped_column(String(1024), nullable=False)  # relative path or object key
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="SET NULL"))
    benchmark_run_id: Mapped[int | None] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="SET NULL"))
    extra: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    dataset: Mapped[Dataset | None] = relationship(back_populates="artifacts")
    __table_args__ = (
        CheckConstraint(_in("artifact_type", ("raster", "table", "figure", "log")), name="type_valid"),
        CheckConstraint(_in("file_format", ("geotiff", "parquet", "csv", "png", "json")), name="format_valid"),
        CheckConstraint("char_length(storage_ref) > 0", name="ref_not_empty"),
        Index("ix_artifacts_dataset", "dataset_id"),
    )


class RegionalAnalytic(Base):
    __tablename__ = "regional_analytics"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    index_name: Mapped[str] = mapped_column(String(8), nullable=False)
    mean: Mapped[float | None] = mapped_column(Float)
    minimum: Mapped[float | None] = mapped_column(Float)
    maximum: Mapped[float | None] = mapped_column(Float)
    std_dev: Mapped[float | None] = mapped_column(Float)
    valid_pixel_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_pixel_count: Mapped[int | None] = mapped_column(BigInteger)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    region: Mapped[Region] = relationship()
    dataset: Mapped[Dataset] = relationship()
    __table_args__ = (
        CheckConstraint(_in("index_name", INDEX_NAMES), name="index_valid"),
        CheckConstraint("valid_pixel_count >= 0", name="valid_nonneg"),
        CheckConstraint("total_pixel_count IS NULL OR total_pixel_count >= valid_pixel_count", name="total_ge_valid"),
        CheckConstraint("minimum IS NULL OR maximum IS NULL OR minimum <= maximum", name="min_le_max"),
        CheckConstraint("mean IS NULL OR minimum IS NULL OR mean >= minimum", name="mean_ge_min"),
        CheckConstraint("mean IS NULL OR maximum IS NULL OR mean <= maximum", name="mean_le_max"),
        UniqueConstraint("region_id", "dataset_id", "index_name", "observation_date", name="uq_regional_analytics_obs"),
        Index("ix_regional_analytics_series", "region_id", "index_name", "observation_date"),
    )


class BenchmarkSuite(Base):
    """One Pandas-vs-PySpark comparison (two BenchmarkRun rows) on one synthetic dataset."""
    __tablename__ = "benchmark_suites"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    workload: Mapped[str] = mapped_column(String(64), default="annual_regional_summary", nullable=False)
    data_kind: Mapped[str] = mapped_column(String(16), default="synthetic", nullable=False)
    requested_rows: Mapped[int] = mapped_column(BigInteger, nullable=False)
    input_rows: Mapped[int | None] = mapped_column(BigInteger)  # ACTUAL rows generated
    trials: Mapped[int] = mapped_column(Integer, nullable=False)
    warmup: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    environment: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    data_generation_s: Mapped[float | None] = mapped_column(Float)  # excluded from every processing time
    speedup: Mapped[float | None] = mapped_column(Float)  # median pandas / median spark; only if outputs matched
    comparison: Mapped[dict | None] = mapped_column(JSONB)  # numerical equivalence report
    error_details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    runs: Mapped[list["BenchmarkRun"]] = relationship(back_populates="suite", order_by="BenchmarkRun.framework",
                                                       foreign_keys="BenchmarkRun.suite_id", cascade="all, delete-orphan")
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="status_valid"),
        CheckConstraint("data_kind = 'synthetic'", name="synthetic_only"),
        CheckConstraint("requested_rows > 0 AND trials >= 1 AND warmup >= 0", name="params_valid"),
        CheckConstraint("speedup IS NULL OR speedup > 0", name="speedup_positive"),
        CheckConstraint("status <> 'failed' OR error_details IS NOT NULL", name="failed_has_error"),
        Index("ix_benchmark_suites_created", "created_at"),
    )


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    framework: Mapped[str] = mapped_column(String(16), nullable=False)
    workload: Mapped[str] = mapped_column(String(64), nullable=False)
    data_kind: Mapped[str] = mapped_column(String(16), default="synthetic", nullable=False)  # synthetic | real
    dataset_size_label: Mapped[str | None] = mapped_column(String(32))  # nominal, e.g. "1M"
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)  # ACTUAL rows processed
    duration_s: Mapped[float | None] = mapped_column(Float)  # mean over `runs`
    duration_sd_s: Mapped[float | None] = mapped_column(Float)
    runs: Mapped[int | None] = mapped_column(Integer)
    throughput_rows_s: Mapped[float | None] = mapped_column(Float)
    speedup: Mapped[float | None] = mapped_column(Float)  # only when a baseline run was measured
    baseline_run_id: Mapped[int | None] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="SET NULL"))
    suite_id: Mapped[int | None] = mapped_column(ForeignKey("benchmark_suites.id", ondelete="CASCADE"))
    init_s: Mapped[float | None] = mapped_column(Float)  # framework initialisation (not in processing time)
    median_s: Mapped[float | None] = mapped_column(Float)
    min_s: Mapped[float | None] = mapped_column(Float)
    max_s: Mapped[float | None] = mapped_column(Float)
    trial_durations: Mapped[list | None] = mapped_column(JSONB)
    valid_rows: Mapped[int | None] = mapped_column(BigInteger)
    output_rows: Mapped[int | None] = mapped_column(BigInteger)
    output_bytes: Mapped[int | None] = mapped_column(BigInteger)
    peak_rss_mb: Mapped[float | None] = mapped_column(Float)  # sampled RSS of the worker process tree (approximate)
    suite: Mapped["BenchmarkSuite | None"] = relationship(back_populates="runs", foreign_keys="BenchmarkRun.suite_id")
    mae: Mapped[float | None] = mapped_column(Float)
    max_abs_err: Mapped[float | None] = mapped_column(Float)
    within_tolerance: Mapped[bool | None] = mapped_column()
    environment: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)  # os, cpu, python, library versions
    status: Mapped[str] = mapped_column(String(16), default="completed", nullable=False)
    error_details: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(_in("framework", FRAMEWORKS), name="framework_valid"),
        CheckConstraint(_in("status", BENCH_STATUSES), name="status_valid"),
        CheckConstraint(_in("data_kind", ("synthetic", "real")), name="data_kind_valid"),
        CheckConstraint("row_count > 0", name="rows_positive"),
        CheckConstraint("duration_s IS NULL OR duration_s >= 0", name="duration_nonneg"),
        CheckConstraint("throughput_rows_s IS NULL OR throughput_rows_s >= 0", name="throughput_nonneg"),
        CheckConstraint("speedup IS NULL OR speedup > 0", name="speedup_positive"),
        Index("ix_benchmark_runs_lookup", "framework", "workload", "row_count"),
        UniqueConstraint("suite_id", "framework", name="uq_benchmark_runs_suite_framework"),
    )
