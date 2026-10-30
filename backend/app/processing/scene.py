"""Scene discovery and metadata. A scene is a folder holding Sentinel-2 L2A band rasters.

Accepted layouts (searched recursively):
  * ESA SAFE:   .../GRANULE/*/IMG_DATA/R10m/T43QCF_20230115T050209_B03_10m.jp2 (and R20m/...)
  * Flat:       B03_10m.tif, B04_10m.tif, B08_10m.tif, B11_20m.tif, SCL_20m.tif  (resolution suffix optional)
Metadata (first match wins): explicit arguments > scene.json manifest > MTD_MSIL2A.xml > filename.
"""
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import rasterio

from .errors import InputError

REQUIRED_BANDS = ("B03", "B04", "B08", "B11")
OPTIONAL_BANDS = ("SCL",)
DATA_KINDS = ("observation", "synthetic_test_fixture")
_BAND_RE = re.compile(r"(?:^|[_\-.])(B03|B04|B08|B11|SCL)(?:[_\-](10|20|60)m)?\.(tif|tiff|jp2)$", re.I)
_DATE_RE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})T\d{6}")
_PREFERRED_RES = {"B03": (10, 20), "B04": (10, 20), "B08": (10, 20), "B11": (20, 10), "SCL": (20,)}


@dataclass
class SceneInfo:
    scene_id: str
    directory: Path
    bands: dict[str, Path]
    acquisition_date: date
    data_kind: str
    boa_add_offset: float
    offset_source: str
    quantification: float
    source: str = "user-supplied"
    notes: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def has_mask(self) -> bool:
        return "SCL" in self.bands


def discover_bands(directory: Path) -> dict[str, Path]:
    found: dict[str, dict[int | None, Path]] = {}
    for p in sorted(directory.rglob("*")):
        if not p.is_file():
            continue
        m = _BAND_RE.search(p.name)
        if m:
            found.setdefault(m.group(1).upper(), {})[int(m.group(2)) if m.group(2) else None] = p
    out = {}
    for band, by_res in found.items():
        for res in (*_PREFERRED_RES[band], None):
            if res in by_res:
                out[band] = by_res[res]
                break
    return out


def _read_manifest(directory: Path) -> dict:
    mf = directory / "scene.json"
    if not mf.is_file():
        return {}
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise InputError("scene.json exists but is not valid JSON.")
    if not isinstance(data, dict):
        raise InputError("scene.json must contain a JSON object.")
    return data


def _mtd_values(directory: Path, tag: str) -> set[float]:
    """Collect numeric values of every element named `tag` in MTD_MSIL2A.xml (namespace-agnostic)."""
    vals: set[float] = set()
    for xml in directory.rglob("MTD_MSIL2A.xml"):
        try:
            for el in ET.parse(xml).iter():
                if el.tag.split("}")[-1] == tag and el.text:
                    vals.add(float(el.text.strip()))
        except (ET.ParseError, ValueError, OSError):
            continue
    return vals


def has_mtd(directory: Path) -> bool:
    return any(True for _ in directory.rglob("MTD_MSIL2A.xml"))


def load_scene(directory: Path, *, acquisition_date: date | None = None, boa_add_offset: float | None = None,
               quantification: float | None = None, data_kind: str | None = None,
               source: str | None = None) -> SceneInfo:
    if not directory.is_dir():
        raise InputError("Scene directory does not exist.")
    bands = discover_bands(directory)
    missing = [b for b in REQUIRED_BANDS if b not in bands]
    if missing:
        raise InputError(f"Missing required band file(s): {', '.join(missing)}. "
                         f"Expected names like B03_10m.tif / T43QCF_20230115T050209_B03_10m.jp2.")
    mf = _read_manifest(directory)
    warnings: list[str] = []

    # acquisition date
    d = acquisition_date
    if d is None and mf.get("acquisition_date"):
        try:
            d = date.fromisoformat(str(mf["acquisition_date"]))
        except ValueError:
            raise InputError("scene.json acquisition_date must be YYYY-MM-DD.")
    if d is None:
        for text in (directory.name, *[p.name for p in bands.values()]):
            m = _DATE_RE.search(text)
            if m:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                break
    if d is None:
        raise InputError("Acquisition date not found. Provide it, add it to scene.json, or use ESA file names.")

    # reflectance offset: never guessed
    off, off_src = boa_add_offset, "argument"
    if off is None and mf.get("boa_add_offset") is not None:
        off, off_src = float(mf["boa_add_offset"]), "scene.json"
    if off is None:
        vals = _mtd_values(directory, "BOA_ADD_OFFSET")
        if len(vals) == 1:
            off, off_src = vals.pop(), "MTD_MSIL2A.xml"
        elif len(vals) > 1:
            raise InputError("MTD_MSIL2A.xml lists different BOA_ADD_OFFSET values per band; set boa_add_offset explicitly.")
    if off is None:
        raise InputError("Reflectance offset (BOA_ADD_OFFSET) is unknown. It is -1000 for processing baseline >= 04.00 "
                         "(from 25 Jan 2022) and 0 before. Provide boa_add_offset or MTD_MSIL2A.xml.")

    q = quantification
    if q is None and mf.get("quantification_value") is not None:
        q = float(mf["quantification_value"])
    if q is None:
        qv = _mtd_values(directory, "BOA_QUANTIFICATION_VALUE")
        q = qv.pop() if len(qv) == 1 else 10000.0
    if q <= 0:
        raise InputError("Quantification value must be positive.")

    kind = data_kind or mf.get("data_kind") or ("observation" if has_mtd(directory) else None)
    if kind is None:
        raise InputError("data_kind is unknown. State 'observation' (real Sentinel-2) or 'synthetic_test_fixture' "
                         "in scene.json or as an argument; it is never assumed.")
    if kind not in DATA_KINDS:
        raise InputError(f"data_kind must be one of {DATA_KINDS}.")

    if "SCL" not in bands:
        warnings.append("No SCL (scene classification) file found: cloud and shadow pixels cannot be masked.")
    return SceneInfo(scene_id=directory.name, directory=directory, bands=bands, acquisition_date=d, data_kind=kind,
                     boa_add_offset=float(off), offset_source=off_src, quantification=float(q),
                     source=source or mf.get("source") or "user-supplied", notes=str(mf.get("notes", "")),
                     warnings=warnings)


def validate_band_files(info: SceneInfo, expected_res=(10.0, 20.0)) -> dict[str, dict]:
    """Open every band; check CRS, size, resolution, nodata metadata. Returns per-band facts."""
    facts: dict[str, dict] = {}
    for band, path in info.bands.items():
        try:
            with rasterio.open(path) as src:
                if src.crs is None:
                    raise InputError(f"{band}: raster has no CRS.")
                if src.width < 1 or src.height < 1 or src.count < 1:
                    raise InputError(f"{band}: raster is empty.")
                res = abs(src.transform.a)
                if not any(abs(res - e) / e < 0.01 for e in expected_res) or abs(abs(src.transform.e) - res) / res > 0.01:
                    raise InputError(f"{band}: unsupported pixel size {res:g} m (expected 10 or 20 m, square pixels).")
                facts[band] = {"crs": src.crs.to_string(), "res_m": res, "width": src.width, "height": src.height,
                               "nodata": src.nodata, "dtype": src.dtypes[0], "file": path.name}
        except rasterio.errors.RasterioIOError:
            raise InputError(f"{band}: file cannot be opened as a raster ({path.name}).")
    crs_set = {f["crs"] for f in facts.values()}
    if len(crs_set) > 1:
        raise InputError("Bands have different CRS; use one Sentinel-2 tile.")
    return facts
