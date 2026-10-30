# GEONOVA

**Scalable Multi-Temporal Satellite Analytics for Environmental Change Detection Using Distributed Data Processing**

A research prototype: Sentinel-2 L2A processing (NDVI, NDWI, NDBI) for Ahmedabad, Surat, Pune and Bengaluru, temporal change
comparison, a Pandas-vs-PySpark (local mode) benchmark, a FastAPI backend with PostgreSQL/PostGIS, and a React dashboard.

> **Honest status.** Everything has been tested on **synthetic** data only. No real Sentinel-2 scene has been processed
> yet, so no environmental finding is claimed. Benchmarks use synthetic tabular data on one machine; they say nothing
> about cluster performance. See [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

Three kinds of data appear in this project and are always labelled:
* **Real satellite observations**: none processed so far.
* **Synthetic test fixtures**: tiny generated rasters used by tests and the demo (`data_kind=synthetic_test_fixture`, hidden in the dashboard unless you tick "Include synthetic test fixtures").
* **Synthetic benchmark data**: generated tables for timing Pandas vs PySpark (`data_kind=synthetic`).

## Features
| Area | What exists | Verified how |
|---|---|---|
| Processing | B03/B04/B08/B11 + SCL -> reflectance -> NDVI/NDWI/NDBI GeoTIFFs, regional statistics (Parquet), two-date change | automated tests on synthetic rasters |
| API | regions, datasets, jobs (background worker), analytics (summary, regional, temporal), benchmarks | pytest against PostgreSQL/PostGIS |
| Database | PostgreSQL 16 + PostGIS, Alembic migrations 0001-0003 | pytest + migration up/down/check |
| Benchmark | deterministic synthetic data, identical Pandas and PySpark workloads, equivalence check, speedup | pytest + measured runs at 100k, 1M, 5M rows |
| Dashboard | Overview, Explorer (colour NDVI/NDWI/NDBI, change and land-cover layers), Temporal, Datasets, Regional, Benchmarks (run + history), Jobs, About | production build + browser walkthrough against the live API |

## Repository layout
```
backend/            FastAPI app (app/), Alembic migrations (alembic/), tests (app/tests), demo script (scripts/)
frontend/           React + Vite dashboard
docs/               ARCHITECTURE, DATABASE, SATELLITE_PROCESSING, BENCHMARK_METHODOLOGY, API, TESTING, KNOWN_LIMITATIONS, FUTURE_SCOPE
scripts/            Windows PowerShell helpers (setup, run backend, run frontend, run tests)
legacy_starter/     original standalone prototype, not used by the app (see its README)
```

## Prerequisites (Windows 11)
* Python 3.11 (tested on 3.11.17), Node.js 18 or newer (tested on 22.22), with npm, PostgreSQL 16 with the PostGIS extension, Java 17 or 21 (PySpark only).
* Details: [backend/README.md](backend/README.md), [docs/DATABASE.md](docs/DATABASE.md), [docs/BENCHMARK_METHODOLOGY.md](docs/BENCHMARK_METHODOLOGY.md).

## Quick start (PowerShell, from the project root)
```powershell
.\scripts\setup_windows.ps1        # venv, pip install, npm install, copies .env.example -> .env
notepad backend\.env               # replace CHANGE_ME with YOUR database password (both URLs)
```
Create the databases once (see docs/DATABASE.md), then:
```powershell
.\scripts\run_backend.ps1          # migrations + seed regions + API on http://localhost:8000  (Swagger: /docs)
.\scripts\run_frontend.ps1         # dashboard on http://localhost:5173   (second terminal)
```
Manual equivalent:
```powershell
cd backend; .\.venv\Scripts\python.exe -m alembic upgrade head; .\.venv\Scripts\python.exe -m app.db.seed
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
cd ..\frontend; npm install; npm run dev
```

## Configuration
* `backend/.env` (copy of `backend/.env.example`): `DATABASE_URL`, `TEST_DATABASE_URL`, `CORS_ORIGINS` (exact origins, comma-separated; the default allows `http://localhost:5173` and `http://127.0.0.1:5173`), `DATA_DIR`, `APP_ENV`.
* `frontend/.env` (copy of `frontend/.env.example`): `VITE_API_BASE_URL=http://localhost:8000`. Restart `npm run dev` after changing it.
* `.env` files are git-ignored and are not in the distributed zip. Never commit passwords.
* POST endpoints work only when `APP_ENV=development` (or `API_WRITES_ENABLED=true`). There is **no authentication**: do not expose the API publicly.

## Try it with synthetic data
```powershell
# backend\.env: add ALLOW_SYNTHETIC_PERSIST=true (demo only; use a throwaway database), restart the API, then:
cd backend; .\.venv\Scripts\python.exe scripts\demo_synthetic_workflow.py
```
Then open Temporal Change or Regional Analytics and tick **Include synthetic test fixtures**. Turn the setting off afterwards.

## Using real Sentinel-2 data
Follow "Getting Sentinel-2 L2A data" in [backend/README.md](backend/README.md) (start with one or two scenes), then
submit a `scene_processing` job. **Check the printed BOA offset and visually inspect the GeoTIFFs in QGIS before trusting any number.**

## Tests
```powershell
.\scripts\run_tests.ps1            # set $env:TEST_DATABASE_URL first (a dedicated *_test database)
```
See [docs/TESTING.md](docs/TESTING.md) for the exact results that were verified.