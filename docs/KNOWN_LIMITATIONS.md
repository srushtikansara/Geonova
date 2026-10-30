# Known limitations and unverified assumptions

## Implementation status
**Complete and verified (on synthetic data / in the build environment):** index calculations and nodata handling, alignment, GeoTIFF and Parquet outputs, change detection, jobs API, database schema and migrations, analytics endpoints, benchmark module and API, dashboard pages (build + browser walkthrough).

**Implemented but not fully verified:**
* Processing of **real** Sentinel-2 products (JP2 reading, SAFE layout, XML offset parsing, SCL conventions).
* **Windows 11**: the setup, migrations, API, frontend and 125 of 127 tests were run there by the user. Spark's native Parquet write fails without `winutils.exe`; the `auto` fallback is unit-tested but not yet re-run on Windows. JP2 driver availability on Windows is unchecked.
* `backend/scripts/fetch_sentinel2.py` (real Sentinel-2 window download from Planetary Computer): window logic tested offline on synthetic files; **the live download has never been run**. `legacy_starter/scripts/fetch_scenes.py` was never run either.

**Incomplete:**
* No authentication/authorisation (local use only). POST endpoints are gated only by `APP_ENV`.
* The Explorer's land-cover classes use fixed threshold rules (NDWI > 0, NDVI >= 0.3, NDBI > 0 with NDVI < 0.2) that have not been validated against reference imagery or ground truth; use them as an indication only. Layers are shown as whole-scene overlays, not map tiles, so very large regions will be coarse (display width capped at 1024 px).
* `backend/scripts/build_timeseries.py` (multi-year download + processing) has not been run against the live service.
* The dashboard cannot submit processing jobs (they need a local scene folder); use the API or CLI. Benchmarks can be started from the dashboard.
* No frontend automated tests or lint configuration.
* Dataset registration endpoint exists, but ingestion (download) is manual.
* Fuzzy/soft-computing land-cover layer was only proposed, not built. If your course requires a soft-computing technique, discuss this with your guide.

**Blocked in the build environment:** real imagery (no Copernicus/Planetary Computer access), Windows testing, a multi-node Spark cluster.

## Scientific caveats
* Index differences are not proof of deforestation, urbanisation or flooding.
* The SCL class list, the 0.05 change threshold and the region boxes are conventions to review, not calibrated values.
* A single date per scene; no seasonal normalisation, no atmospheric/BRDF checks, no mosaics.

## Benchmark caveats
* Synthetic data, one machine, local-mode Spark; 3-5 trials per size; no significance tests; no cluster claims.
* The memory estimate is a heuristic calibrated on three measurements; peak RSS is sampled.
* In these runs Pandas was faster at 100k, 1M and 5M rows; this does not generalise to larger data, other workloads or clusters.
* Measured on the author's Windows machine (5 trials + 1 warm-up, median, outputs verified equal, all PASS): speedup (Pandas / Spark) 0.014-0.016 at 100k rows, 0.164 at 1M and 0.489 at 5M. Pandas was faster at every size and the gap narrowed as data grew. Whether or where Spark overtakes Pandas was not measured.
* The satellite processing pipeline (rasterio/NumPy) does not run on Spark; only the benchmark workload does. Spark's advantage is expected for data larger than one machine's memory or on a cluster; neither was tested.
* On Windows, Spark's Parquet write falls back to a collect-based write (no winutils), which is recorded in each run's environment.

## Operations
* One worker thread per job type: jobs run sequentially; a job running when the server restarts stays `running`.
* Paths in stored artifacts are relative to `DATA_DIR`; moving that folder requires keeping the structure.
* The test database is truncated by the test suite: never point `TEST_DATABASE_URL` at a database you care about.
* Multi-year series pick the clearest scene in a January-March window, so scene dates differ between years (for example mid-January in one year, mid-March in another). Vegetation can change within that span, so year-to-year differences include seasonal effects.
* On Windows, a PostgreSQL/PostGIS install can set PROJ_LIB/PROJ_DATA to an older proj.db; the backend overrides this with the data bundled with rasterio (see `app/__init__.py`).
* Observed on the author's machine: Ahmedabad, Surat and Bengaluru were each downloaded and processed for 2021-2026 (6 scenes, 5 NDVI change jobs, all reported completed). These outputs have not been validated against reference data or checked in QGIS.