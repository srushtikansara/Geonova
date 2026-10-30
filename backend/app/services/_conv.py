"""ORM -> API schema conversion."""
from app.db import models as m
from app import schemas as s


def region_out(r: m.Region, analysed: bool = False) -> s.Region:
    return s.Region(id=r.code, name=r.name, state=r.state, country=r.country,
                    bbox=[r.min_lon, r.min_lat, r.max_lon, r.max_lat], notes=r.description,
                    configured=True, analysed=analysed)


def dataset_out(d: m.Dataset) -> s.DatasetOut:
    return s.DatasetOut(id=d.id, name=d.name, source=d.source, mission=d.mission, sensor=d.sensor,
                        acquisition_date=d.acquisition_date, region=d.region.code, status=d.status,
                        processing_baseline=d.processing_baseline, metadata=d.extra or {}, created_at=d.created_at)


def job_out(j: m.AnalysisJob) -> s.Job:
    return s.Job(id=str(j.id), status=j.status, kind=j.job_type, created_utc=j.created_at,
                 region=j.region.code if j.region else None, dataset_id=j.dataset_id, index_name=j.index_name,
                 started_utc=j.started_at, completed_utc=j.completed_at, error_details=j.error_details,
                 params=j.params or {}, result=j.result or {})


def benchmark_out(b: m.BenchmarkRun) -> s.BenchmarkOut:
    return s.BenchmarkOut(
        id=b.id, benchmark_id=b.suite_id, framework=b.framework, engine=b.framework, workload=b.workload,
        data_kind=b.data_kind, data=b.data_kind, dataset_size_label=b.dataset_size_label, row_count=b.row_count,
        records=b.row_count, valid_rows=b.valid_rows, output_rows=b.output_rows, output_bytes=b.output_bytes,
        duration_s=b.duration_s, mean_s=b.duration_s, median_s=b.median_s, min_s=b.min_s, max_s=b.max_s,
        sd_s=b.duration_sd_s, runs=b.runs, trial_durations=b.trial_durations, init_s=b.init_s,
        peak_rss_mb=b.peak_rss_mb, throughput=b.throughput_rows_s, speedup=b.speedup, mae=b.mae,
        max_abs_err=b.max_abs_err, within_tolerance=b.within_tolerance, environment=b.environment or {},
        status=b.status, error_details=b.error_details, started_at=b.started_at, finished_at=b.finished_at)


def suite_out(x: m.BenchmarkSuite, with_runs: bool = False) -> s.SuiteOut:
    return s.SuiteOut(
        id=x.id, status=x.status, workload=x.workload, data_kind=x.data_kind, requested_rows=x.requested_rows,
        input_rows=x.input_rows, trials=x.trials, warmup=x.warmup, seed=x.seed, config=x.config or {},
        environment=x.environment or {}, data_generation_s=x.data_generation_s, speedup=x.speedup,
        comparison=x.comparison, error_details=x.error_details, created_at=x.created_at, started_at=x.started_at,
        finished_at=x.finished_at, run_ids=[r.id for r in x.runs],
        runs=[benchmark_out(r) for r in x.runs] if with_runs else None)
