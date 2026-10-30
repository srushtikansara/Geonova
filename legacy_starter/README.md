# LEGACY starter harness (kept for reference)

This folder is the original standalone prototype (STAC scene fetching + an early Pandas/PySpark harness). It is NOT used by the backend or frontend. The supported benchmark module is `backend/app/benchmark/`. `scripts/fetch_scenes.py` (real data download) has never been run by the authors. Run its tests from this folder: `python -m pytest tests`.

# GEONOVA code (starter)

Sentinel-2 L2A -> NDVI/NDWI/NDBI per city/year -> Pandas vs PySpark (local mode).

## Status (honest)
* Tested here ONLY on synthetic data: unit tests pass (6/6) and Pandas and Spark agree within tolerance on synthetic records.
* `scripts/fetch_scenes.py` (real data) is UNTESTED: run it on your laptop.
* Synthetic numbers are for testing/benchmarks only. They are NOT findings.
* No real results exist yet; report only what the CSVs in `outputs/` contain.

## Setup (Windows 11, PowerShell)
1. Install Python 3.11 or 3.12 and Java 17 (Spark needs Java; check `java -version`).
2. `python -m venv .venv` then `.venv\Scripts\activate`
3. `pip install -r requirements.txt`
4. Spark on Windows may need `winutils`/HADOOP_HOME warnings handled; if Parquet writes fail, tell me the error.

## Run
```
pytest -q tests                                   # sanity checks
python scripts/fetch_scenes.py --max-scenes 3     # quick trial, 3 scenes per city
python scripts/fetch_scenes.py                    # full year (heavy)
python scripts/run_experiments.py                 # Experiments A and D -> outputs/
python -m geonova.benchmark --sizes 100000 1000000 5000000 --runs 10   # Experiment B (synthetic)
python -m geonova.benchmark --master "local[1]" --out outputs/benchmark_local1.csv
```

## Before trusting results
* Check the city boxes in `config.yaml`.
* Check the printed `offset=` per scene (should be -1000 for baseline >= 04.00, else 0).
* Open a few scenes visually to sanity-check masks.
* Experiment C (variants) is not built yet; Experiment B memory column is Python driver RSS only, not the Spark JVM.
