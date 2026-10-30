# Database

PostgreSQL 16 + PostGIS. Driver: psycopg 3 (`postgresql+psycopg://`). Migrations: Alembic (`backend/alembic/versions`):
`0001_initial_schema`, `0002_job_params_and_result`, `0003_benchmark_suites`. The app never creates tables itself.

## Create the databases (Windows 11)
Install PostgreSQL 16 (EnterpriseDB installer), then PostGIS through Stack Builder (Spatial Extensions). In **SQL Shell (psql)** as `postgres`:
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
Put the password in `backend\.env` (`DATABASE_URL`, `TEST_DATABASE_URL`). URL-encode special characters (`@ : / %`).

## Migrate and seed
```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head   # apply
.\.venv\Scripts\python.exe -m alembic current        # expect 0003 (head)
.\.venv\Scripts\python.exe -m alembic check          # models and migrations agree
.\.venv\Scripts\python.exe -m app.db.seed            # Ahmedabad, Surat, Pune, Bengaluru (safe to repeat)
```

## Tables
| Table | Purpose and notable constraints |
|---|---|
| `regions` | code (unique), name, bbox, PostGIS `geom` POLYGON/EPSG:4326 with a GiST index; bbox check constraint |
| `datasets` | one scene/product per row; FK region; JSONB `metadata` (includes `data_kind`); unique (region, name) |
| `analysis_jobs` | UUID id; status queued/running/completed/failed; JSONB params/result; `error_details` required when failed |
| `regional_analytics` | per region, dataset, date, index: mean/min/max/std, valid and total pixel counts; unique per observation; check constraints (min <= mean <= max, valid <= total) |
| `artifacts` | references (`storage_ref`, relative path) to GeoTIFF/Parquet outputs; FKs to dataset, job or benchmark run |
| `benchmark_suites` | one Pandas-vs-PySpark comparison: status, config, environment, speedup, equivalence report |
| `benchmark_runs` | one framework's measured run: trials, median/min/max, init time, peak RSS, rows, throughput, MAE/max error |

## Test database safety
The test suite uses only `TEST_DATABASE_URL`, refuses to start unless the database name ends in `_test`, migrates it at the start,
truncates tables before each test and downgrades at the end. Your real `geonova` database is never touched by pytest.
If `TEST_DATABASE_URL` is unset or unreachable, database tests are **skipped** (and reported as skipped, not passed).
Backup before experimenting: `pg_dump -U geonova_user -d geonova -f geonova_backup.sql`.