from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import ClassSummary, RasterLayerList
from app.services import rasters as svc

router = APIRouter(prefix="/rasters", tags=["rasters"])


def _png(png: bytes, bounds: list) -> Response:
    return Response(png, media_type="image/png", headers={
        "Cache-Control": "private, max-age=300",
        "X-Bounds": ",".join(f"{v:.6f}" for pair in bounds for v in pair),  # south,west,north,east (EPSG:4326)
        "Access-Control-Expose-Headers": "X-Bounds"})


@router.get("/layers", response_model=RasterLayerList)
def layers(region: str | None = Query(None, description="Region code"),
           include_synthetic: bool = Query(False, description="Include synthetic test fixtures (never real observations)"),
           db: Session = Depends(get_db)) -> RasterLayerList:
    """Processed index and change rasters that can be drawn on the map, with bounds and legend."""
    return svc.list_layers(db, region, include_synthetic)


@router.get("/classes/{dataset_id}", response_model=ClassSummary)
def class_summary(dataset_id: int, db: Session = Depends(get_db)) -> ClassSummary:
    """Share of valid pixels per indicative land-cover class (threshold rules, not validated)."""
    return svc.class_summary(db, dataset_id)


@router.get("/classes/{dataset_id}/preview.png")
def class_preview(dataset_id: int, db: Session = Depends(get_db)) -> Response:
    return _png(*svc.class_png(db, dataset_id))


@router.get("/{artifact_id}/preview.png")
def preview(artifact_id: str, db: Session = Depends(get_db)) -> Response:
    """Colour-coded transparent PNG of one raster layer, reprojected to EPSG:4326 (see `bounds` in /layers)."""
    return _png(*svc.layer_png(db, artifact_id))
