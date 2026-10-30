# API

Base URL `http://localhost:8000/api` (interactive docs: `/docs`). JSON everywhere. Errors: `{"detail": "..."}` with 404 not found,
409 conflict, 422 invalid input, 503 database unavailable (messages contain no paths or credentials). POST endpoints need
`APP_ENV=development` (or `API_WRITES_ENABLED=true`), otherwise 403. No authentication: local use only.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/system/info` | version, environment, CORS origins, feature availability (database, PostGIS, PySpark); never secrets |
| GET | `/regions`, `/regions/{code}` | configured regions; `analysed` is true only with real (non-synthetic) results |
| POST | `/regions` | add a region (`code`, `name`, `bbox`) |
| GET | `/datasets?region=&status=&limit=&offset=` , `/datasets/{id}` | registered scenes |
| POST | `/datasets` | register dataset metadata |
| GET | `/jobs?status=`, `/jobs/{id}` | job status and result |
| POST | `/jobs` | `scene_processing` or `change_detection` (run in a background worker); other types stay queued |
| GET | `/analytics/summary` | regions analysed / scenes processed (`include_synthetic=true` to include fixtures) |
| GET | `/analytics/regional?region=&include_synthetic=` | per region and index: observations, latest statistics, coverage, first-to-latest mean change |
| GET | `/analytics/temporal?index=&region=&date_from=&date_to=&include_synthetic=` | time series of regional means |
| GET | `/benchmarks` | measured runs (`items`) and benchmark suites (`suites`); empty state has a `note` |
| POST | `/benchmarks` | queue a benchmark (202); `confirm=true` required for >= 1,000,000 rows |
| GET | `/benchmarks/{id}`, `/benchmarks/runs/{run_id}` | a benchmark with both framework runs, or one run |
| GET | `/benchmarks/preflight?rows=N` | memory/disk estimate and Spark prerequisites; starts nothing |
| POST | `/benchmarks/{id}/cancel` | cancel a queued or running benchmark |

## Examples (PowerShell; the numbers are illustrative of the shape, not results)
```powershell
curl http://localhost:8000/api/health
# {"status":"ok","service":"GEONOVA API","version":"0.1.0","time_utc":"..."}

curl http://localhost:8000/api/regions/pune
# {"id":"pune","name":"Pune","state":"Maharashtra","country":"India","bbox":[73.74,18.45,73.99,18.65],"configured":true,"analysed":false,...}

curl http://localhost:8000/api/analytics/summary
# {"available":false,"regions_analysed":0,"scenes_processed":0,"reason":"No analysis has been run yet."}

curl -Method POST http://localhost:8000/api/jobs -ContentType application/json -Body '{"job_type":"scene_processing","region":"pune","params":{"scene_path":"pune/<SCENE>.SAFE"}}'
# 201 {"id":"<uuid>","status":"queued", ...}; poll GET /api/jobs/<uuid> until completed or failed

curl -Method POST http://localhost:8000/api/benchmarks -ContentType application/json -Body '{"rows":100000,"trials":5,"warmup":1}'
# 202 {"id":1,"status":"queued","requested_rows":100000,"data_kind":"synthetic",...}
curl "http://localhost:8000/api/benchmarks/preflight?rows=1000000"
# {"rows":1000000,"estimated_peak_mb":...,"available_mb":...,"memory_ok":true,"requires_confirmation":true,"spark":{"available":true,...}}
```
Benchmark request fields: `rows` (100..20,000,000), `trials` (1..30), `warmup` (0..5), `seed`, `regions`, `spark_master` (`local[*]` or `local[N]` only),
`shuffle_partitions`, `spark_driver_memory`, `spark_write` (`auto` default | `native` | `collect`), `keep_artifacts`, `confirm`.
