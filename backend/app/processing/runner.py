"""Background job execution: one worker thread, DB-tracked status. No external task queue.

Raster work runs in a ThreadPoolExecutor so the FastAPI event loop is never blocked.
Job states: queued -> running -> completed | failed. Errors are stored without local paths.
"""
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import models as m
from app.db.session import new_session
from . import scene as scene_mod
from .errors import ProcessingError
from .paths import DataPaths
from .pipeline import Params, process_scene, run_change

log = logging.getLogger("geonova.jobs")
RUNNABLE = ("scene_processing", "change_detection")
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="geonova-job")


def data_paths() -> DataPaths:
    root = Path(get_settings().data_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root  # relative to backend/
    return DataPaths(root).ensure()


def submit(job_id: str) -> None:
    if get_settings().jobs_run_inline:
        run_job(job_id)
    else:
        _executor.submit(run_job, job_id)


def _now():
    return datetime.now(timezone.utc)


def _params_from(d: dict) -> Params:
    from datetime import date
    kw = {}
    if d.get("indices"): kw["indices"] = tuple(d["indices"])
    if d.get("target_resolution"): kw["target_resolution"] = int(d["target_resolution"])
    if d.get("valid_scl_classes"): kw["valid_scl_classes"] = tuple(int(x) for x in d["valid_scl_classes"])
    if d.get("allow_missing_mask"): kw["allow_missing_mask"] = bool(d["allow_missing_mask"])
    if d.get("acquisition_date"): kw["acquisition_date"] = date.fromisoformat(d["acquisition_date"])
    for k in ("boa_add_offset", "quantification"):
        if d.get(k) is not None: kw[k] = float(d[k])
    for k in ("data_kind", "source"):
        if d.get(k): kw[k] = d[k]
    return Params(**kw)


def run_job(job_id: str) -> None:
    db = new_session()
    try:
        job = db.get(m.AnalysisJob, uuid.UUID(job_id))
        if job is None or job.status != "queued":
            return
        job.status, job.started_at = "running", _now()
        db.commit()
        try:
            paths = data_paths()
            if job.job_type == "scene_processing":
                result = _scene_job(db, job, paths)
            elif job.job_type == "change_detection":
                result = _change_job(db, job, paths)
            else:
                raise ProcessingError(f"Job type '{job.job_type}' has no runner.")
            job.status, job.result, job.error_details = "completed", result, None
        except ProcessingError as e:
            db.rollback()
            _fail(db, job_id, str(e))
            return
        except Exception:  # noqa: BLE001 - never leak internals to the API
            db.rollback()
            log.exception("job %s failed", job_id)
            _fail(db, job_id, "Unexpected processing error. See the server log for details.")
            return
        job.completed_at = _now()
        db.commit()
    finally:
        db.close()


def _fail(db: Session, job_id: str, message: str) -> None:
    job = db.get(m.AnalysisJob, uuid.UUID(job_id))
    job.status, job.error_details, job.completed_at = "failed", message[:2000], _now()
    db.commit()


def _scene_job(db: Session, job: m.AnalysisJob, paths: DataPaths) -> dict:
    p = job.params or {}
    if job.region is None:
        raise ProcessingError("A region is required.")
    directory = paths.resolve_ref(str(p.get("scene_path", "")), paths.raw)
    params = _params_from(p)
    info = scene_mod.load_scene(directory, acquisition_date=params.acquisition_date, boa_add_offset=params.boa_add_offset,
                                quantification=params.quantification, data_kind=params.data_kind, source=params.source)
    if info.data_kind != "observation" and not get_settings().allow_synthetic_persist:
        raise ProcessingError("Synthetic test fixtures are not stored in the database (ALLOW_SYNTHETIC_PERSIST is off). "
                              "Use the command-line tool for files-only processing.")
    r = job.region
    res = process_scene(directory, r.code, [r.min_lon, r.min_lat, r.max_lon, r.max_lat], paths, params)

    kind = res.data_kind
    ds = db.scalar(select(m.Dataset).where(m.Dataset.region_id == r.id, m.Dataset.name == res.scene_id))
    meta = {"data_kind": kind, "limitations": res.limitations, "parameters": res.parameters, "grid": res.grid, **res.metadata}
    if ds is None:
        ds = m.Dataset(name=res.scene_id, source=res.source, mission="Sentinel-2" if kind == "observation" else "SYNTHETIC-FIXTURE",
                       sensor="MSI L2A" if kind == "observation" else "synthetic", acquisition_date=_d(res.acquisition_date),
                       region_id=r.id, status="processing", extra=meta)
        db.add(ds)
        db.flush()
    else:
        ds.acquisition_date, ds.source, ds.extra, ds.status = _d(res.acquisition_date), res.source, meta, "processing"
    job.dataset_id = ds.id

    refs = [v["raster_ref"] for v in res.indices.values()] + [res.summary_ref]
    db.execute(delete(m.Artifact).where(m.Artifact.dataset_id == ds.id, m.Artifact.storage_ref.in_(refs)))
    art_ids = {}
    for name, v in res.indices.items():
        a = m.Artifact(id=uuid.uuid4(), artifact_type="raster", file_format="geotiff", storage_ref=v["raster_ref"],
                       dataset_id=ds.id, job_id=job.id,
                       extra={"index": name, "formula": v["formula"], "input_bands": v["input_bands"],
                              "resolution_m": res.grid["resolution_m"], "data_kind": kind})
        db.add(a)
        art_ids[name] = a.id
    db.add(m.Artifact(artifact_type="table", file_format="parquet", storage_ref=res.summary_ref, dataset_id=ds.id,
                      job_id=job.id, extra={"kind": "scene_summary", "data_kind": kind}))
    db.flush()
    stored = 0
    for name, v in res.indices.items():
        st = v["stats"]
        db.execute(delete(m.RegionalAnalytic).where(
            m.RegionalAnalytic.region_id == r.id, m.RegionalAnalytic.dataset_id == ds.id,
            m.RegionalAnalytic.index_name == name, m.RegionalAnalytic.observation_date == ds.acquisition_date))
        if st["valid_pixel_count"] == 0:
            continue  # nothing valid to report: do not create an analysis record
        lo, hi = st["min"], st["max"]
        mean = min(max(st["mean"], lo), hi)  # guard float rounding against the min<=mean<=max constraint
        db.add(m.RegionalAnalytic(region_id=r.id, dataset_id=ds.id, observation_date=ds.acquisition_date, index_name=name,
                                  mean=mean, minimum=lo, maximum=hi, std_dev=st["std"],
                                  valid_pixel_count=st["valid_pixel_count"], total_pixel_count=st["total_pixel_count"],
                                  artifact_id=art_ids[name]))
        stored += 1
    ds.status = "processed" if stored else "failed"
    if not stored:
        raise ProcessingError("No valid pixels remained after masking (for example, a fully cloudy scene).")
    db.flush()
    out = res.to_dict()
    out["dataset_id"] = ds.id
    return out


def _d(s: str):
    from datetime import date
    return date.fromisoformat(s)


def _change_job(db: Session, job: m.AnalysisJob, paths: DataPaths) -> dict:
    p = job.params or {}
    idx = job.index_name or p.get("index")
    if job.region is None or idx is None:
        raise ProcessingError("A region and an index are required.")
    refs = {}
    for key in ("earlier_dataset_id", "later_dataset_id"):
        ds = db.get(m.Dataset, int(p.get(key, -1)))
        if ds is None or ds.region_id != job.region.id:
            raise ProcessingError(f"{key} does not refer to a dataset in region '{job.region.code}'.")
        art = db.scalar(select(m.Artifact).where(m.Artifact.dataset_id == ds.id, m.Artifact.artifact_type == "raster",
                                                 m.Artifact.extra["index"].astext == idx))
        if art is None:
            raise ProcessingError(f"Dataset {ds.id} has no processed {idx.upper()} raster. Process the scene first.")
        refs[key] = art.storage_ref
    out = run_change(paths.resolve_ref(refs["earlier_dataset_id"]), paths.resolve_ref(refs["later_dataset_id"]), paths,
                     region_code=job.region.code, align=bool(p.get("align", True)),
                     **({"threshold": float(p["threshold"])} if p.get("threshold") is not None else {}))
    kind = out["summary"]["data_kind"]
    db.add(m.Artifact(artifact_type="raster", file_format="geotiff", storage_ref=out["change_raster_ref"], job_id=job.id,
                      extra={"index": idx, "kind": "change", "data_kind": kind, **{k: p[k] for k in ("earlier_dataset_id", "later_dataset_id")}}))
    db.add(m.Artifact(artifact_type="table", file_format="parquet", storage_ref=out["summary_ref"], job_id=job.id,
                      extra={"kind": "change_summary", "data_kind": kind}))
    return {**out, "interpretation": "Spectral-index change; not a validated land-cover transition."}
