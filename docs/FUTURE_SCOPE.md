# Future scope

Planned or suggested extensions. None of these are implemented or measured yet.

## Big-data scaling (Pandas vs PySpark)
* Run the benchmark on a real cluster or managed Spark service (for example a multi-node cluster or a cloud service) instead of local mode on one machine.
* Test data sizes larger than one machine's memory, where distributed processing is expected to help, and report whether and where PySpark overtakes Pandas.
* Add heavier workloads (joins, group-by over many regions and dates, per-pixel statistics) as separate, clearly labelled benchmarks.
* Move the pixel-level processing of real Sentinel-2 scenes to a distributed engine (for example Spark with raster/geospatial libraries) and store results in partitioned Parquet.
* Repeat the benchmark with real pixel tables, not only synthetic data, and add significance tests over more trials.

## Satellite analysis
* Validate land-cover classes and index changes against reference imagery or ground truth (for example high-resolution imagery or official land-use maps).
* Reduce seasonal effects: fixed narrow date windows, seasonal composites or median mosaics instead of one scene per year.
* Add more cities, more indices and more years; add more tiles per city when a region spans several.
* Replace fixed-threshold land-cover rules with a fuzzy or learned classifier (soft-computing / machine-learning approach), evaluated against reference data.

## System
* Run jobs on a proper queue (for example Celery or a workflow engine) instead of a single worker thread.
* Serve map layers as tiles for large regions.
* Add authentication, deployment to a server and scheduled monitoring of newly released scenes.