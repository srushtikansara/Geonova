# Architecture

```
Browser (React + Vite, :5173) --HTTP/JSON--> FastAPI (:8000, /api) --SQLAlchemy--> PostgreSQL + PostGIS
                                                  |  \--> background worker thread (processing jobs)
                                                  |  \--> background worker thread (benchmark suites)
                                                  v
                                   DATA_DIR/ (GeoTIFF + Parquet files; the database stores only references)
Benchmark suite --spawns--> subprocess (Pandas)   and   subprocess (PySpark local mode, JVM)
```

## Components
| Component | Location | Responsibility |
|---|---|---|
| Frontend | `frontend/src` | Pages call the API through `src/api/services.js` (axios, base URL from `VITE_API_BASE_URL`). Every page has loading, error and empty states; nothing is hardcoded. |
| API | `backend/app/api/routes` | Thin routes, Pydantic schemas in `app/schemas`, business logic in `app/services`. Errors map to 404/409/422/503 without leaking paths or credentials. |
| Database | `backend/app/db`, `backend/alembic` | Models and migrations. See DATABASE.md. |
| Processing | `backend/app/processing` | `scene` (find bands, metadata), `raster` (read, align, mask), `indices`, `stats`, `change`, `pipeline`, `runner` (job execution + DB persistence), `cli` (no database needed). |
| Benchmark | `backend/app/benchmark` | `generate` (deterministic synthetic data), `workload_pandas`, `workload_spark`, `worker` (subprocess entry), `compare`, `orchestrator`, `runner` (DB persistence), `cli`. |

## Data flow: satellite processing
1. A scene folder (Sentinel-2 L2A bands + SCL) sits under `DATA_DIR/raw/<region>/`.
2. `POST /api/jobs` (`scene_processing`) stores a queued job and returns at once (HTTP 201). One worker thread runs it.
3. The worker validates files, converts DN to reflectance, aligns bands to one grid, masks by SCL, computes indices.
4. Outputs: float32 GeoTIFFs (nodata -9999) and a Parquet summary under `DATA_DIR/processed/`.
5. The worker upserts the dataset, `regional_analytics` rows and artifact references, then marks the job completed or failed (with a safe message).
6. The dashboard polls `GET /api/jobs/{id}` and reads `GET /api/analytics/*`.
A `change_detection` job subtracts two processed rasters (later minus earlier) and stores a change GeoTIFF and summary.

## Data flow: benchmark
`POST /api/benchmarks` validates the request, checks memory, stores a **queued** suite and returns 202. The worker generates
the synthetic Parquet, runs Pandas and PySpark each in their own subprocess (clean memory and start-up numbers, cancellable),
compares outputs, computes the speedup only if they agree, stores both runs, and deletes the temporary input.
Nothing is ever started when the API starts.

## Design decisions
* Rasters and tables stay on disk; PostgreSQL holds metadata and references (small, queryable, backup-friendly).
* Synthetic data is marked at the source (`data_kind`) and filtered out of analytics unless explicitly requested.
* Single worker thread per job type: simple and safe on a laptop; an in-flight job is lost on restart (see KNOWN_LIMITATIONS).
* CORS is an exact-origin allow-list from `CORS_ORIGINS`; a wildcard is rejected when `APP_ENV=production`.
