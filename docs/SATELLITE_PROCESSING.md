# Satellite processing

> **Verification status:** only small **synthetic test rasters** (generated arrays, `data_kind=synthetic_test_fixture`) have been
> processed. **No real Sentinel-2 product has been processed**, so nothing here is validated against real imagery.

## Inputs (Sentinel-2 Level-2A, surface reflectance)
| Band | Use | Native resolution |
|---|---|---|
| B03 (green) | NDWI | 10 m |
| B04 (red) | NDVI | 10 m |
| B08 (NIR) | NDVI, NDWI, NDBI | 10 m |
| B11 (SWIR1) | NDBI | 20 m |
| SCL (scene classification) | cloud / invalid mask | 20 m |

Files are searched recursively under the scene folder (`..._B04_10m.jp2` or `.tif`). Provenance comes from `MTD_MSIL2A.xml` or a
`scene.json` (`acquisition_date`, `boa_add_offset`, `data_kind`, `source`). Scene paths are relative to `DATA_DIR/raw`; absolute paths and `..` are refused.

## Steps and formulas
1. **Validate**: required bands present, readable, same CRS family, plausible resolution; otherwise the job fails with a specific message.
2. **Reflectance** = (DN + BOA_ADD_OFFSET) / 10000. DN 0 and the file nodata become NaN. The offset (-1000 for processing baseline 04.00 and later, i.e. from 25 Jan 2022; 0 before) is **never guessed**: it must come from an argument, `scene.json` or the XML, else the scene is rejected.
3. **Align** to one grid (default 20 m): 10 m bands are block-averaged (valid sub-pixels only); `--resolution 10` upsamples B11 bilinearly; SCL always uses nearest neighbour.
4. **Mask**: keep SCL classes 4, 5, 6, 7 (vegetation, not vegetated, water, unclassified; configurable). A missing SCL is an error unless explicitly allowed, and then the result says "NO cloud mask applied".
5. **Indices**
   * NDVI = (B8 - B4) / (B8 + B4)
   * NDWI (McFeeters) = (B3 - B8) / (B3 + B8)
   * NDBI = (B11 - B8) / (B11 + B8)
   NaN/inf inputs, a non-positive band sum, or |result| > 1 produce nodata (-9999), so there is no division by zero.
6. **Regional statistics** over valid pixels whose centre lies inside the region box (reprojected to the raster CRS): mean, min, max, sample SD, valid and total pixel counts, coverage.
7. **Outputs**: float32 GeoTIFF per index (deflate, nodata -9999, same CRS and transform as the grid, tags INDEX, FORMULA, INPUT_BANDS, ACQUISITION_DATE, RESOLUTION_M, DATA_KIND ...), a Parquet summary, and database rows (dataset, `regional_analytics`, artifact references).
8. **Change (later - earlier)**: if grids differ, the later raster is resampled onto the earlier one (refused if they barely overlap); outputs a change GeoTIFF plus mean/min/max/SD and proportions below, near, above a threshold (default |change| <= 0.05, a convention, not calibrated).

## How to run
* Without a database: `python -m app.processing.cli process --scene-dir <dir> --region pune`, then `... change --region pune --earlier <tif> --later <tif>`, `... inspect <file>`.
* Through the API: `POST /api/jobs` with `job_type` `scene_processing` or `change_detection` (see API.md).
* Repeatable synthetic demo: `python backend/scripts/demo_synthetic_workflow.py` (needs `ALLOW_SYNTHETIC_PERSIST=true` on a throwaway database).

## Interpretation and limitations
* A difference in an index is a **spectral-index change**, not proof of deforestation, urbanisation or flooding: season, residual cloud/shadow, sun-sensor geometry and processing baseline also move it.
* The region boxes in `app/data/regions.json` are approximate; review them before analysis.
* No BRDF/topographic correction, no scene-level QA beyond SCL, no mosaics (one tile per scene), one tile may not cover a whole city.
* The XML offset parsing was written from documented tag names and tested only with a synthetic XML. JP2 reading needs GDAL's JP2 driver (present in the Linux rasterio wheel used here; **not checked on Windows**). Confirm the printed offset and open the first outputs in QGIS.
