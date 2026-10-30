"""Download small WINDOWS of real Sentinel-2 L2A scenes (free, no account) for a configured region.

Source: Microsoft Planetary Computer STAC API (collection "sentinel-2-l2a"), which serves cloud-optimised GeoTIFFs.
Only the pixels inside the region box are downloaded (tens of MB per scene, not the 0.5-1 GB product).
Output goes to <DATA_DIR>/raw/<region>/<scene>/ in exactly the layout the processing pipeline reads
(B03/B04/B08 at 10 m, B11 and SCL at 20 m, plus scene.json with the acquisition date and BOA offset).

    pip install -r requirements-fetch.txt
    python scripts/fetch_sentinel2.py --region pune --start 2023-01-01 --end 2023-03-31 --max-cloud 10 --max-scenes 2

STATUS: the download path has NOT been run against the live service by its author (no network access in the build
environment). The window-writing logic is tested offline with local files. Check the first scene yourself.
No credentials are needed or stored. Data licence: Copernicus Sentinel data (free, open); credit "Contains modified
Copernicus Sentinel data".
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rasterio  # noqa: E402
from rasterio.warp import transform_bounds  # noqa: E402
from rasterio.windows import Window, from_bounds  # noqa: E402

BANDS = {"B03": 10, "B04": 10, "B08": 10, "B11": 20, "SCL": 20}
SOURCE = "Microsoft Planetary Computer (sentinel-2-l2a)"


def boa_offset_from_baseline(baseline: str | None) -> int:
    """Processing baseline >= 04.00 (from 25 Jan 2022) has BOA_ADD_OFFSET = -1000; earlier is 0. Never guessed."""
    if not baseline:
        raise ValueError("The scene has no processing baseline, so the BOA offset cannot be determined. Skipping it.")
    return -1000 if float(baseline) >= 4.0 else 0


def region_bbox(code: str) -> list[float]:
    regions = json.loads((Path(__file__).resolve().parents[1] / "app" / "data" / "regions.json").read_text(encoding="utf-8"))
    items = regions["items"] if isinstance(regions, dict) and "items" in regions else regions
    for r in items:
        if r.get("id", r.get("code")) == code:
            return list(r["bbox"])
    raise SystemExit(f"Unknown region '{code}'. Known: {[r.get('id', r.get('code')) for r in items]}")


def write_window(src_href: str, bbox_wgs84: list[float], dest: Path) -> dict:
    """Read only the pixels inside bbox (min_lon, min_lat, max_lon, max_lat) and write them as a GeoTIFF."""
    with rasterio.open(src_href) as src:
        left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *bbox_wgs84, densify_pts=21)
        win = from_bounds(left, bottom, right, top, transform=src.transform).round_offsets().round_lengths()
        win = win.intersection(Window(0, 0, src.width, src.height))
        if win.width < 2 or win.height < 2:
            raise ValueError("The region does not overlap this scene.")
        data = src.read(1, window=win)
        profile = src.profile | {"driver": "GTiff", "height": data.shape[0], "width": data.shape[1],
                                 "transform": src.window_transform(win), "count": 1, "compress": "deflate", "tiled": False}
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(dest, "w", **profile) as out:
            out.write(data, 1)
        return {"width": data.shape[1], "height": data.shape[0], "crs": str(src.crs)}


def fetch_scene(hrefs: dict[str, str], bbox: list[float], out_dir: Path, stem: str, meta: dict) -> Path:
    """Write all bands for one scene plus scene.json. `stem` looks like T43PGP_20230115T050209."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for band, res in BANDS.items():
        if band not in hrefs:
            raise ValueError(f"The scene has no {band} asset.")
        write_window(hrefs[band], bbox, out_dir / f"{stem}_{band}_{res}m.tif")
    (out_dir / "scene.json").write_text(json.dumps({**meta, "data_kind": "observation", "source": SOURCE}, indent=2), encoding="utf-8")
    return out_dir


def fetch_region_scenes(region: str, start: str, end: str, max_cloud: float, max_scenes: int, root: Path) -> list[dict]:
    """Search Planetary Computer and download up to `max_scenes` of the least cloudy scenes. Returns one dict per scene."""
    import planetary_computer
    import pystac_client
    bbox = region_bbox(region)
    cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=planetary_computer.sign_inplace)
    search = cat.search(collections=["sentinel-2-l2a"], bbox=bbox, datetime=f"{start}/{end}",
                        query={"eo:cloud_cover": {"lt": max_cloud}}, max_items=200)
    items = sorted(search.items(), key=lambda i: i.properties.get("eo:cloud_cover", 100))
    print(f"{len(items)} candidate scene(s) with cloud cover < {max_cloud}%")
    done = []
    for it in items:
        if len(done) >= max_scenes:
            break
        p = it.properties
        try:
            offset = boa_offset_from_baseline(p.get("s2:processing_baseline"))
            day = p["datetime"][:10]
            stem = f"T{p.get('s2:mgrs_tile', 'XXXXX')}_{p['datetime'][:19].replace('-', '').replace(':', '')}"
            hrefs = {b: it.assets[b].href for b in BANDS if b in it.assets}
            out = fetch_scene(hrefs, bbox, root / "raw" / region / it.id, stem,
                              {"acquisition_date": day, "boa_add_offset": offset, "stac_item": it.id,
                               "scene_cloud_cover_percent": p.get("eo:cloud_cover"), "processing_baseline": p.get("s2:processing_baseline")})
        except Exception as e:  # noqa: BLE001
            print(f"SKIP {it.id}: {type(e).__name__}: {e}")
            continue
        print(f"OK   {it.id} ({day}, cloud {p.get('eo:cloud_cover')}%) -> {out}")
        done.append({"scene_id": it.id, "date": day, "cloud": p.get("eo:cloud_cover"), "path": str(out)})
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", required=True, help="region code from app/data/regions.json, e.g. pune")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--max-cloud", type=float, default=10.0, help="scene-level cloud cover limit, percent")
    ap.add_argument("--max-scenes", type=int, default=2)
    ap.add_argument("--data-dir", default=None, help="defaults to DATA_DIR or backend/data")
    a = ap.parse_args()
    try:
        import planetary_computer  # noqa: F401
        import pystac_client  # noqa: F401
    except ImportError:
        print("ERROR: install the fetch dependencies first: pip install -r requirements-fetch.txt")
        return 2
    from app.processing.runner import data_paths
    root = Path(a.data_dir) if a.data_dir else data_paths().root
    done = fetch_region_scenes(a.region, a.start, a.end, a.max_cloud, a.max_scenes, root)
    for d in done:
        print('     job: {"job_type":"scene_processing","region":"%s","params":{"scene_path":"%s/%s"}}' % (a.region, a.region, d["scene_id"]))
    print(f"{len(done)} scene(s) downloaded.")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
