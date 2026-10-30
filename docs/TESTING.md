# Testing

Status of each check, from the last full run (sandbox: Linux, 2 CPUs; **Python 3.11.17, pandas 2.3.3, PySpark 4.2.1, Java 21.0.12,
PostgreSQL 16 + PostGIS**). Re-run on your machine; results here are for that environment only.

## Commands
```powershell
cd backend
$env:TEST_DATABASE_URL = "postgresql+psycopg://geonova_user:<your-password>@localhost:5432/geonova_test"   # dedicated *_test database
.\.venv\Scripts\python.exe -m pytest app/tests -q -rs     # -rs lists skipped tests; a skip is NOT a pass
.\.venv\Scripts\python.exe -m alembic check               # needs DATABASE_URL; models and migrations agree
cd ..\frontend; npm ci; npm run build
cd ..\legacy_starter; python -m pytest tests               # optional: legacy prototype
```

## Results
| Check | Result | Notes |
|---|---|---|
| Backend pytest (`backend/app/tests`), Linux sandbox | **PASS** 128 passed, 0 skipped | includes PostgreSQL/PostGIS and PySpark tests |
| Backend pytest on Windows 11 (user's machine, first run) | 125 passed, **2 failed** | both Spark tests failed on the missing `winutils.exe`; fixed by `spark_write=auto` (re-verify on Windows) |
| Database tests (migrations up/down, PostGIS, geometry/GiST, FKs, constraints, cascade, rollback, empty queries) | **PASS** | `test_db.py`, `test_errors.py`, fixtures in `conftest.py`; test DB only |
| `alembic check` | **PASS** | no new upgrade operations |
| Satellite-processing tests (indices, division by zero, nodata, CRS, alignment, timestamps, GeoTIFF/Parquet outputs, change) | **PASS** 23 core + 14 job/API tests | **synthetic rasters only** |
| Real Sentinel-2 validation | **NOT RUN** | no real scene available in the build environment (no Copernicus access) |
| Benchmark tests (determinism, workload equivalence, known values, tolerances, speedup, invalid configs, failure reporting, API) | **PASS** 32 core + 21 API | Spark-dependent tests ran (Java 21 present) |
| Real small benchmark (100k, 1M, 5M rows) | **PASS** | see BENCHMARK_METHODOLOGY.md; all outputs agreed |
| Frontend production build (`npm run build`) | **PASS** | chunk-size warning only |
| Frontend tests / lint | **NOT RUN** | none configured in `package.json` |
| Frontend <-> backend browser walkthrough (all 8 pages, headless Chromium, live API + PostgreSQL) | **PASS** | no failed API calls; only map-tile requests failed because the sandbox has no internet |
| End-to-end synthetic workflow via HTTP (`scripts/demo_synthetic_workflow.py`) | **PASS** | scene jobs, change job, GeoTIFF CRS/nodata, temporal API |
| Legacy starter tests (`legacy_starter/tests`) | **PASS** 6 | not part of the app |

## What the tests do and do not show
* Mutation checks were done by hand on the speedup formula and sample SD: the tests failed as they should.
* Synthetic fixtures prove the code does what it says on known inputs. They do not prove the results are right for real imagery.
* Small benchmark tests prove correctness, not performance.
* Tests never touch your real database: `TEST_DATABASE_URL` must end in `_test`, and the suite refuses to run otherwise.
* The authors' build environment is Linux. The first Windows run (by the user) found the winutils problem above; everything else in that run passed. Not every PowerShell script has been confirmed on Windows.
