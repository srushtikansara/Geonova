# GEONOVA backend (Phases 3-4: PostgreSQL/PostGIS + satellite processing)

FastAPI + SQLAlchemy 2 + GeoAlchemy2 + Alembic + Rasterio + Pandas/PySpark benchmarking. See `../docs/` for the full documentation.
Empty tables return valid empty results; nothing is invented. See **Satellite processing** below.

## 1. Prerequisites (Windows 11)
* Python 3.11, and PostgreSQL 16 (EnterpriseDB installer). During install keep the default port 5432 and remember the `postgres` password.
* PostGIS: at the end of the PostgreSQL installer choose **Stack Builder** -> *Spatial Extensions* -> **PostGIS** (bundle for your PostgreSQL version). Accept the defaults. (If you skipped it, run Stack Builder from the Start menu.)

## 2. Create the databases (psql as the `postgres` superuser)
Open **SQL Shell (psql)** (or add `C:\Program Files\PostgreSQL\16\bin` to PATH) and run:
```sql
CREATE ROLE geonova_user LOGIN PASSWORD 'choose-your-own-password' CREATEDB;
CREATE DATABASE geonova      OWNER geonova_user;
CREATE DATABASE geonova_test OWNER geonova_user;
\c geonova
CREATE EXTENSION IF NOT EXISTS postgis;
\c geonova_test
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT postgis_version();
```
Creating the extension needs a superuser, which is why you do it here once. `geonova_test` is used only by the tests.

## 3. Configure `.env`
```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env      # replace CHANGE_ME with your password in BOTH URLs
```
`.env` is git-ignored. If your password has special characters (`@ : / %`), URL-encode them.

## 4. Run the migrations and seed the regions
```powershell
python -m alembic upgrade head      # creates all tables, indexes and constraints
python -m alembic current           # should show 0001 (head)
python -m app.db.seed               # adds Ahmedabad, Surat, Pune, Bengaluru (safe to repeat)
```
Other useful commands: `python -m alembic downgrade -1`, `python -m alembic check`.
The app never creates tables by itself.

## 5. Start the API
```powershell
python -m uvicorn app.main:app --reload --port 8000
```
* API http://127.0.0.1:8000/api, Swagger http://127.0.0.1:8000/docs
* `GET /api/system/info` shows whether the database is reachable and PostGIS is enabled.
* If the database is down, data routes return **503**; `/api/health` still works.

## 6. Tests
```powershell
python -m pytest -q
```
Tests use only `TEST_DATABASE_URL` (database name must end with `_test`; the suite refuses to start otherwise and overwrites `DATABASE_URL` in-process so your real database is never touched). The test database is migrated at start, truncated before each test, and downgraded at the end.
If `TEST_DATABASE_URL` is unset or unreachable, the database tests are **skipped**, and pytest says so. A skipped run is not a pass.

## Schema
`regions` (code unique, bbox, PostGIS `geom` POLYGON/4326 with GiST index) 1-* `datasets` (FK, status, JSONB metadata, unique (region, name))
`analysis_jobs` (UUID, status queued/running/completed/failed, FKs to region/dataset, error_details required when failed)
`regional_analytics` (region, dataset, observation_date, index, mean/min/max/std, valid_pixel_count; unique per observation)
`benchmark_runs` (framework pandas/spark, workload, actual row_count, duration, throughput, optional speedup/mae/max_abs_err, environment JSONB)
`artifacts` (type raster/table/figure/log, format geotiff/parquet/csv/png/json, `storage_ref` path; FKs to dataset/job/benchmark).
Rasters stay on disk as GeoTIFF, tables as Parquet; the database stores only references.

## API summary
GET /api/regions, /api/regions/{code}, POST /api/regions
GET /api/datasets (filters: region, status, limit, offset), /api/datasets/{id}, POST /api/datasets
GET /api/analytics/summary, /api/analytics/regional, /api/analytics/temporal?index=&region=&date_from=&date_to= (all accept include_synthetic=true)
GET/POST /api/benchmarks, GET /api/benchmarks/{id}, /api/benchmarks/runs/{id}, /api/benchmarks/preflight (see Phase 5 below)
GET /api/jobs (filter: status), /api/jobs/{id}, POST /api/jobs (scene_processing and change_detection run in a background worker)
POST endpoints are enabled when `APP_ENV=development` (override with `API_WRITES_ENABLED`) and return 403 otherwise. There is no authentication yet, so do not expose this server publicly.

## Importing measured benchmarks
```powershell
python -m app.db.import_benchmarks ..\outputs\benchmark.csv
```
Rows come from the harness CSV (`python -m geonova.benchmark`). Speedup is computed only when both engines were measured on the same row count and configuration. Benchmarks on synthetic data measure speed only.

## Limitations (Phase 3 items)
* No authentication.

---------------------------------------------------------------------------------------------------

# Satellite processing (Phase 4)

> **Status:** verified ONLY on small *synthetic* test rasters (generated arrays, labelled `synthetic_test_fixture`).
> No real Sentinel-2 product has been processed yet. Run one real scene on your machine before trusting any number.

## What it does
Reads Sentinel-2 L2A bands (B03, B04, B08, B11 + SCL cloud/scene-classification), clips to a configured region, aligns
all bands to one grid, masks invalid/cloudy pixels, computes NDVI / NDWI (McFeeters) / NDBI, writes GeoTIFFs and a
Parquet summary, and compares two dates (later - earlier).

| Index | Formula | Bands |
|---|---|---|
| NDVI | (B8 - B4) / (B8 + B4) | B08, B04 |
| NDWI (McFeeters) | (B3 - B8) / (B3 + B8) | B03, B08 |
| NDBI | (B11 - B8) / (B11 + B8) | B11, B08 |

**Index validity rules:** NaN/inf input, denominator <= 0, or |result| > 1 -> nodata (no division by zero).

## Processing rules (documented choices)
* **Reflectance** = (DN + BOA_ADD_OFFSET) / quantification (10000). DN 0 and the file's nodata value become NaN.
  The offset is **never guessed**: it comes from an argument, `scene.json`, or `MTD_MSIL2A.xml`; otherwise the scene is rejected.
  (It is -1000 for processing baseline >= 04.00, i.e. from 25 Jan 2022, and 0 before.)
* **Grid:** default **20 m** (design decision D1). B03/B04/B08 (10 m) are block-averaged onto the B11 20 m grid with GDAL
  `average` (mean of valid sub-pixels). `--resolution 10` instead upsamples B11 with `bilinear`. SCL is always `nearest`.
  The method used is stored in each result's `limitations`.
* **Cloud mask:** SCL classes kept as valid: 4 vegetation, 5 not vegetated, 6 water, 7 unclassified (configurable).
  A missing SCL file is an **error** unless you explicitly allow it; then results are flagged "NO cloud mask applied".
* **Region:** the WGS84 box is densified, reprojected to the raster CRS, and a pixel counts if its **centre** is inside.
  Boxes in `regions.json` are approximate. Statistics use valid pixels only (mean, min, max, sample SD, valid and total counts, coverage).
* **Change** = later - earlier. Different CRS/transform -> the later raster is resampled onto the earlier grid (refused if
  `--no-align` or if they barely overlap). Proportions use a threshold (default |change| <= 0.05 is "near zero"; an adjustable
  convention, **not** a calibrated value). Changes are described as *spectral-index changes*, never as deforestation,
  urbanisation or flooding.
* **Provenance:** every output records `data_kind` (`observation` or `synthetic_test_fixture`), acquisition date, source,
  parameters and limitations. It is never inferred silently: state it in `scene.json`/arguments, or provide `MTD_MSIL2A.xml`.
  Synthetic fixtures are **not stored in the database** unless `ALLOW_SYNTHETIC_PERSIST=true` (tests only), and even then
  they never make a region "analysed" or appear in analytics unless `include_synthetic=true` is requested.

## Getting Sentinel-2 L2A data, option A: automatic small download (recommended)
Free, no account. Downloads only the pixels inside the region box (tens of MB per scene) from Microsoft's Planetary Computer.
```powershell
cd backend
pip install -r requirements-fetch.txt
python scripts\fetch_sentinel2.py --region pune --start 2023-01-01 --end 2023-03-31 --max-cloud 10 --max-scenes 2
```
It prints, for each scene, the exact `POST /api/jobs` body to submit. **The download part has not been run against the live
service by the author** (no network access in the build environment); the window-writing logic is tested offline.
If it fails, send the error text. Pick two dates in different years (same season) if you want a change comparison.

### Several years in one go (for the multi-year view)
With the API running:
```powershell
python scripts\build_timeseries.py --region ahmedabad --years 2021 2022 2023 2024 2025 --season 01-01 03-31
```
It downloads one clear scene per year (same season), processes each, and compares consecutive years. Not yet run against the live service.

## Getting Sentinel-2 L2A data, option B: manual download (start small: 1-2 scenes)
1. Create a free account at https://dataspace.copernicus.eu/ and open the **Copernicus Browser**.
2. Search **Sentinel-2 -> L2A**, draw a box over Pune (or Ahmedabad/Surat), choose a dry-season date, set max cloud cover ~10-20%.
3. Download the product (a `.zip`, roughly 0.5-1 GB) and unzip it. Never put credentials in this project or in git.
4. Place the unzipped `.SAFE` folder under `backend/data/raw/<region>/`, e.g.
   `backend/data/raw/pune/S2B_MSIL2A_20230115T050209_N0509_R019_T43QCF_....SAFE/`.
   Any layout works if the band files can be found (searched recursively): `..._B03_10m.jp2`, `..._B04_10m.jp2`,
   `..._B08_10m.jp2`, `..._B11_20m.jp2`, `..._SCL_20m.jp2` (or the same names as `.tif`). `MTD_MSIL2A.xml` supplies the offset.
5. For a hand-made folder (no XML), add `scene.json` next to the bands:
```json
{"acquisition_date": "2023-01-15", "boa_add_offset": -1000, "data_kind": "observation", "source": "Copernicus Data Space"}
```
(The XML parsing is written from the documented tag names `BOA_ADD_OFFSET` / `BOA_QUANTIFICATION_VALUE` and tested only with a synthetic XML - confirm the printed `offset_source`/offset on your first real scene.)

## Run it without a database (files-only development mode)
```powershell
cd backend
python -m app.processing.cli process --scene-dir data\raw\pune\<SCENE> --region pune
python -m app.processing.cli change --region pune --earlier <ndvi_tif_date1> --later <ndvi_tif_date2>
python -m app.processing.cli inspect data\processed\indices\pune\<file>.tif
python -m app.processing.cli inspect data\processed\summaries\pune\<file>.parquet
```
Nothing is saved to PostgreSQL in this mode. Output goes to `data\processed\{indices,changes,summaries}\<region>\`
(change `DATA_DIR` in `.env` to move it). On failure the tool prints `ERROR: ...` and exits with code 2.

## Run it through the API (needs the database from the previous phase)
`POST /api/jobs` (when `APP_ENV=development`). The request returns immediately with `status: queued`; a single background
worker thread does the raster work (the event loop is never blocked). Poll `GET /api/jobs/{id}`; states are
queued -> running -> completed | failed. Failures store a safe message (no local paths) and the server log has details.
```json
{"job_type": "scene_processing", "region": "pune",
 "params": {"scene_path": "pune/<SCENE>.SAFE", "indices": ["ndvi","ndwi","ndbi"], "target_resolution": 20}}
```
Optional params: `valid_scl_classes`, `allow_missing_mask`, `acquisition_date`, `boa_add_offset`, `data_kind`, `source`.
`scene_path` is relative to `data/raw` (absolute paths and `..` are refused). A completed job creates/updates the dataset,
artifact references (GeoTIFF + Parquet paths, never the rasters themselves) and `regional_analytics` rows, so Overview,
Temporal and Regional pages fill in. Re-running a scene replaces its records (idempotent).
```json
{"job_type": "change_detection", "region": "pune", "index_name": "ndvi",
 "params": {"earlier_dataset_id": 1, "later_dataset_id": 2, "threshold": 0.05}}
```
Job types other than these two are stored as `queued` only.
Swagger: http://127.0.0.1:8000/docs

## Inspecting outputs
* GeoTIFF (float32, nodata -9999, deflate): open in QGIS, or `python -m app.processing.cli inspect <file>.tif` for CRS,
  pixel size and the tags (INDEX, FORMULA, INPUT_BANDS, ACQUISITION_DATE, RESOLUTION_M, SOURCE_DATASET, DATA_KIND, ...).
* Parquet: `python -c "import pandas as pd; print(pd.read_parquet(r'<file>').T)"`.

## Tests
`python -m pytest -q` runs 70+ tests (processing + database). Processing tests build tiny synthetic scenes in a temp
folder (nothing is committed), so no credentials, downloads or real imagery are needed.

## Limitations and known issues
* **Not verified on real Sentinel-2 data.** JP2 reading needs GDAL's JP2 driver (present in the Linux rasterio wheel I used; not checked on Windows).
* The first real product may reveal layout/metadata differences (SAFE paths, XML tags, nodata/saturation handling).
* Averaging 10 -> 20 m uses valid sub-pixels only; B11 is not sharpened. Reflectance below zero after the offset is kept, and any pixel with a non-positive band sum is invalid.
* The default SCL class list and the 0.05 change threshold are conventions to be justified/tuned, not validated.
* No atmospheric or BRDF checks, no scene-level QA beyond SCL, and no multi-scene mosaics (one tile per scene).
* Region areas that fall outside the scene are not counted; this is recorded as a limitation on that result.
* Single worker thread: jobs run one at a time and an in-flight job is lost if the server restarts (it stays `running`).
* No authentication; do not expose the API publicly. Spark/Pandas benchmarking is a separate phase.

---

# Pandas vs PySpark benchmarking (Phase 5)

Compares Pandas and PySpark (**local mode, one machine**) on an identical workload over a **SYNTHETIC**
dataset. Nothing here is real Sentinel-2 data, and nothing here says anything about a cluster.

## Java and PySpark setup (Windows 11)

PySpark needs a JVM. Spark 4.x documents support for **Java 17 or 21** (Python 3.9+). In the development
sandbox PySpark 4.2.1 ran on Java 21 (OpenJDK 21.0.12). Check what you have:

```powershell
java -version
echo $env:JAVA_HOME
```

If Java is missing or older than 17, install a JDK 17 or 21 (for example Eclipse Temurin), then set `JAVA_HOME`
to the JDK folder (the one containing `bin\java.exe`):

```powershell
# current terminal only
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-21.0.x-hotspot"
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
# permanently (new terminals): setx JAVA_HOME "C:\Program Files\Eclipse Adoptium\jdk-21.0.x-hotspot"
```

Install the Python dependencies (`pip install -r requirements.txt`; this pins `pandas<3`, which PySpark 4 supports
best). `GET /api/system/info` (feature `pyspark_benchmarks`) and `GET /api/benchmarks/preflight` report whether Spark
can start and why not. If it cannot, the benchmark is recorded as **failed with the exact cause**; Pandas results are
never substituted for Spark.

**Windows (verified on a real Windows 11 test run):** Spark's native local Parquet write needs Hadoop's `winutils.exe`
(`HADOOP_HOME`). Without it, Spark starts fine but the write fails with "HADOOP_HOME and hadoop.home.dir are unset".
The default `spark_write=auto` therefore uses Spark's native writer everywhere **except Windows without winutils**, where it
collects the three small result tables to the driver and writes them with PyArrow (`collect`). The effective mode is stored
with every Spark run (`environment.spark_write`) and shown in the benchmark detail. It changes what the Spark timing contains
(the write step is no longer done by Spark), so report it whenever you quote a Windows number. To use the native writer on
Windows, install a `winutils.exe` matching your Hadoop version and set `HADOOP_HOME` to the folder that contains `bin\winutils.exe`.

## Run a small benchmark (no database needed)

```powershell
cd backend
python -m app.benchmark.cli --rows 100000 --trials 5 --warmup 1
```

Output goes to `<DATA_DIR>/benchmarks/cli-<timestamp>/result.json` (override with `DATA_DIR`). Nothing is ever
overwritten; each run gets its own folder, and generated input data is deleted afterwards unless `--keep-input` (CLI) or `keep_artifacts` (API).

## Run larger benchmarks safely

* 1,000,000 rows or more requires `--confirm-large` (CLI) or `"confirm": true` (API). The dashboard shows a
  confirmation panel with the estimated memory/disk and Spark status first.
* The estimate is a **heuristic**: `700 MB + 420 MB per million rows`. It is deliberately conservative: in the
  development sandbox, measured peak memory was 0.5-1.5 GB at 1M and 5M rows (see "Measured runs").
  A run is refused if the estimate exceeds 70% of currently available RAM.
* A benchmark never starts when the API starts. `POST /api/benchmarks` only queues work (202); one benchmark runs
  at a time; `POST /api/benchmarks/{id}/cancel` stops it and kills the worker process trees.
* Large files live under the benchmark directory (`data/benchmarks/` is git-ignored).

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/benchmarks` | Queue a benchmark (`rows`, `trials`, `warmup`, `seed`, `regions`, `spark_master`, `shuffle_partitions`, `spark_driver_memory`, `spark_write`, `keep_artifacts`, `confirm`) |
| GET | `/api/benchmarks` | Measured per-framework runs (`items`) and benchmark suites (`suites`) |
| GET | `/api/benchmarks/{benchmark_id}` | One benchmark (status queued/running/completed/failed, both framework runs, comparison) |
| GET | `/api/benchmarks/runs/{run_id}` | One framework run |
| GET | `/api/benchmarks/preflight?rows=N` | Memory/disk estimate and Spark prerequisites; starts nothing |
| POST | `/api/benchmarks/{id}/cancel` | Cancel a queued or running benchmark |

## Workload (identical in both frameworks)

Input columns: `observation_id, region_id, observation_date, ndvi, ndwi, ndbi, valid_pixel_count`
(generated with a fixed seed; ~2% null indices, ~1% out-of-range, ~3% zero pixel counts so the filter has work to do).

1. **Filter invalid**: keep rows where all three indices are non-null, finite, within [-1, 1], and `valid_pixel_count > 0`.
2. **Annual summary**: group by (`region_id`, year) -> `obs_count`, `valid_pixel_sum`, mean NDVI/NDWI/NDBI,
   sample standard deviation of NDVI, min/max NDVI, pixel-weighted mean NDVI.
3. **Regional summary**: group by region over the valid raw rows (not a mean of annual means).
4. **Annual change**: difference of annual means versus the previous year **only when the gap is exactly one year**.
5. Write the three tables to Parquet.

## Metric definitions

* **Processing time (per trial)**: read input Parquet -> filter -> aggregate -> write output Parquet.
  **Excluded**: data generation (reported separately), framework start-up (`init_s`, reported separately), warm-up runs.
* **Trials**: `warmup` unreported runs, then `trials` measured runs. Every trial duration is stored, with
  median, min, max, mean and SD. The **median** is used for speedup and throughput.
* **Throughput** = input rows / median processing time.
* **Speedup = Pandas median / PySpark median.** Above 1: PySpark was faster. Below 1: Pandas was faster. It is only
  computed when both frameworks completed **and** the outputs agreed.
* **Peak memory**: sampled (every 50 ms) resident memory of the worker process tree, including the Spark JVM.
  Approximate; Pandas and Spark numbers are not directly comparable.
* **Equivalence check**: results are sorted by key; counts, years and pixel sums must match exactly; floats must satisfy
  `|a-b| <= 1e-12 + 1e-9*|b|`; NaN/null positions must match. MAE and max absolute error are reported.
  A mismatch marks the benchmark **failed** and no speedup is stored.
* Each framework runs in its own subprocess, so memory and initialisation are not polluted by the other.

## Measured runs (development sandbox; SYNTHETIC data, seed 42)

Sandbox: 2 logical CPUs, 8 GB RAM, Linux, **Python 3.11.17, pandas 2.3.3** (the pinned `requirements.txt`), PySpark 4.2.1,
Java 21.0.12, Spark `local[*]`, 1 warm-up run per framework. These are single-machine results, not representative of your
laptop, and not of a cluster. Re-run on your own hardware before quoting any number.

| Rows | Trials | Pandas median s | PySpark median s | Speedup (Pandas/Spark) | Spark init s | Peak RSS MB (Pandas / Spark) | Agreement |
|---:|---:|---:|---:|---:|---:|---:|---|
| 100,000 | 5 | 0.066 | 2.568 | 0.026 | 10.1 | 199 / 1128 | PASS |
| 1,000,000 | 3 | 0.358 | 4.455 | 0.080 | 10.4 | 463 / 1016 | PASS |
| 5,000,000 | 3 | 1.954 | 10.331 | 0.189 | 10.4 | 1471 / 1490 | PASS |

(An earlier set of runs on the same machine with Python 3.13 / pandas 3.0.5 gave the same picture: speedups 0.029, 0.095, 0.162.)

Reading this honestly: on this 2-core machine, for this workload and these sizes, **Pandas was faster at every size**.
The gap narrows as rows grow (speedup 0.026 -> 0.080 -> 0.189), which is consistent with Spark's fixed per-job overhead
being amortised, but three sizes on one machine do not establish where (or whether) a crossover would occur, and say
nothing about multi-node clusters, larger-than-memory data, or other workloads.

## Interpreting results and limitations

* Spark in local mode runs in one JVM on your CPU cores; it adds scheduling, serialisation and shuffle overhead that a
  cluster would spread across machines. Pandas is expected to win on small data that fits in memory.
* Only 1-3 data points per size and 3-5 trials: spread is shown, but no significance testing is done.
* Peak memory is sampled and approximate. The memory heuristic is calibrated against three measurements only.
* Results depend on disk speed, CPU, Java version, Spark configuration (`shuffle_partitions`, driver memory) and the
  Windows `spark_write` mode. Spark and Pandas versions are stored with each result.

## Tests

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://user:pass@localhost:5432/geonova_test"   # a DEDICATED test DB
python -m pytest app/tests -q -rs
```

`-rs` lists skipped tests. Spark tests (`@pytest.mark.spark`) skip automatically when Java/PySpark is unavailable, and
database tests skip when `TEST_DATABASE_URL` is unset; a skipped test is NOT a pass. Tests use tiny synthetic data and
verify correctness, not performance.