"""Map layers built from processed rasters (artifact references). Colours are applied on demand; nothing new is stored."""
import uuid
from pathlib import Path

import rasterio
from rasterio.warp import transform_bounds
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.core.errors import Invalid, NotFound
from app.db import models as m
from app.processing import render
from app.processing.errors import InputError
from app.processing.runner import data_paths


def _legend(kind: str, index: str) -> s.Legend:
    sc = (render.CHANGE_SCALES if kind == "change" else render.SCALES)[index]
    return s.Legend(label=sc["label"], caption=sc["caption"], stops=[s.LegendStop(value=v, colour=c) for v, c in sc["stops"]])


def _path(ref: str) -> Path:
    try:
        p = data_paths().resolve_ref(ref)
    except InputError as e:
        raise Invalid(str(e))
    if not p.is_file():
        raise NotFound("The raster file for this layer is missing on disk.")
    return p


def _bounds(path: Path) -> list[list[float]]:
    with rasterio.open(path) as src:
        w, so, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
    return [[so, w], [n, e]]


def _kind(extra: dict) -> str:
    return (extra or {}).get("data_kind", "observation")


def list_layers(db: Session, region: str | None, include_synthetic: bool) -> s.RasterLayerList:
    arts = db.scalars(select(m.Artifact).where(m.Artifact.artifact_type == "raster", m.Artifact.file_format == "geotiff")
                      .order_by(m.Artifact.created_at)).all()
    ds_by_id = {d.id: d for d in db.scalars(select(m.Dataset))}
    reg = {r.id: r.code for r in db.scalars(select(m.Region))}
    items = []
    for a in arts:
        ex, kind = a.extra or {}, _kind(a.extra)
        if kind == "synthetic_test_fixture" and not include_synthetic:
            continue
        idx = ex.get("index")
        if idx not in render.SCALES:
            continue
        try:
            path = data_paths().resolve_ref(a.storage_ref)
            if not path.is_file():
                continue
            b = _bounds(path)
        except Exception:  # noqa: BLE001 - an unreadable file must not break the listing
            continue
        if ex.get("kind") == "change":
            e, l = ds_by_id.get(ex.get("earlier_dataset_id")), ds_by_id.get(ex.get("later_dataset_id"))
            if not (e and l):
                continue
            code = reg.get(l.region_id)
            layer = s.RasterLayer(id=str(a.id), kind="change", index=idx, region=code, earlier_date=e.acquisition_date,
                                  later_date=l.acquisition_date, dataset_id=l.id, data_kind=kind, bounds=b, legend=_legend("change", idx))
        else:
            d = ds_by_id.get(a.dataset_id)
            if not d:
                continue
            layer = s.RasterLayer(id=str(a.id), kind="index", index=idx, region=reg.get(d.region_id), date=d.acquisition_date,
                                  dataset_id=d.id, data_kind=kind, bounds=b, legend=_legend("index", idx))
        if region and layer.region != region:
            continue
        items.append(layer)
    items.sort(key=lambda x: (x.region or "", x.date or x.later_date, x.kind, x.index))
    note = f"{len(items)} raster layer(s)." if items else "No processed rasters exist yet. Process a scene first."
    return s.RasterLayerList(items=items, count=len(items), note=note)


def _artifact(db: Session, artifact_id: str) -> m.Artifact:
    try:
        uid = uuid.UUID(artifact_id)
    except ValueError:
        raise Invalid("artifact id must be a UUID")
    a = db.get(m.Artifact, uid)
    if a is None or a.artifact_type != "raster":
        raise NotFound(f"Raster layer {artifact_id} not found")
    return a


def layer_png(db: Session, artifact_id: str) -> tuple[bytes, list]:
    a = _artifact(db, artifact_id)
    ex = a.extra or {}
    idx = ex.get("index")
    if idx not in render.SCALES:
        raise Invalid("This raster has no known index.")
    return render.index_png(_path(a.storage_ref), "change" if ex.get("kind") == "change" else "index", idx)


def _class_inputs(db: Session, dataset_id: int):
    d = db.get(m.Dataset, dataset_id)
    if d is None:
        raise NotFound(f"Dataset {dataset_id} not found")
    arts = {(a.extra or {}).get("index"): a for a in db.scalars(
        select(m.Artifact).where(m.Artifact.dataset_id == dataset_id, m.Artifact.artifact_type == "raster"))}
    missing = [i for i in ("ndvi", "ndwi", "ndbi") if i not in arts]
    if missing:
        raise Invalid("Land-cover classes need NDVI, NDWI and NDBI rasters for this dataset; missing: " + ", ".join(missing))
    return d, [_path(arts[i].storage_ref) for i in ("ndvi", "ndwi", "ndbi")], _kind(d.extra)


def class_png(db: Session, dataset_id: int) -> tuple[bytes, list]:
    _d, paths, _k = _class_inputs(db, dataset_id)
    png, b, _f = render.class_png(*paths)
    return png, b


def class_summary(db: Session, dataset_id: int) -> s.ClassSummary:
    d, paths, kind = _class_inputs(db, dataset_id)
    _png, b, frac = render.class_png(*paths)
    rg = db.get(m.Region, d.region_id)
    classes = [{"code": c, "key": k, "label": lab, "colour": col, **frac[k]} for c, k, lab, col in render.CLASSES]
    return s.ClassSummary(dataset_id=d.id, region=rg.code if rg else None, date=d.acquisition_date, data_kind=kind, bounds=b,
                          valid_pixels=frac["valid_pixels"], classes=classes, rules=render.CLASS_RULES, note=render.CLASS_NOTE)
