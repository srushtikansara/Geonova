"""The benchmark workload, PySpark (DataFrame API, local mode). Logically identical to workload_pandas.py.

Spark-specific, documented choices: shuffle partitions default to the local core count (the Spark default of 200
would dominate a small local job); the filtered data and the annual table are cached because the pandas version
also keeps them in memory and reuses them (without caching Spark would re-scan the input per output table).
"""
import os
import time
from pathlib import Path

COLS = ["observation_id", "region_id", "observation_date", "ndvi", "ndwi", "ndbi", "valid_pixel_count"]
INDICES = ["ndvi", "ndwi", "ndbi"]


def start_spark(master: str, shuffle_partitions: int | None, driver_memory: str):
    """Create the local session and force JVM start-up. Returns (spark, init_seconds)."""
    t0 = time.perf_counter()
    from pyspark.sql import SparkSession
    cores = os.cpu_count() or 2
    parts = shuffle_partitions or (cores if master == "local[*]" else int(master[6:-1]))
    spark = (SparkSession.builder.master(master).appName("geonova-benchmark")
             .config("spark.driver.memory", driver_memory)
             .config("spark.sql.shuffle.partitions", str(parts))
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.ansi.enabled", "false")
             .config("spark.ui.enabled", "false").config("spark.ui.showConsoleProgress", "false")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    spark.range(1).count()  # force JVM/executor start so it is counted as initialisation, not as workload
    return spark, time.perf_counter() - t0


def _is_windows() -> bool:
    return os.name == "nt"


def winutils_present() -> bool:
    """True when Hadoop's Windows helper (bin/winutils.exe) can be found via HADOOP_HOME / hadoop.home.dir."""
    home = os.environ.get("HADOOP_HOME") or os.environ.get("hadoop.home.dir")
    return bool(home) and (Path(home) / "bin" / "winutils.exe").is_file()


def resolve_write_mode(requested: str = "auto") -> str:
    """'auto' -> 'native' (Spark's own Parquet writer), except on Windows without winutils, where Spark's
    native local write fails; there it becomes 'collect' (collect the small result tables, write with PyArrow).
    The effective mode is always recorded with the result: it changes what the Spark timing contains."""
    if requested != "auto":
        return requested
    return "collect" if _is_windows() and not winutils_present() else "native"


def run(spark, input_path: Path, out_dir: Path, write_mode: str = "auto") -> dict:
    from pyspark.sql import Window
    from pyspark.sql import functions as F
    write_mode = resolve_write_mode(write_mode)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = spark.read.parquet(str(input_path)).select(*COLS)
    cond = F.col("valid_pixel_count") > 0
    for c in INDICES:
        cond = cond & F.col(c).between(-1.0, 1.0)  # null -> null -> row dropped
    v = (df.filter(cond).withColumn("year", F.year("observation_date"))
         .withColumn("w_ndvi", F.col("ndvi") * F.col("valid_pixel_count")).persist())

    def agg(keys):
        out = v.groupBy(*keys).agg(
            F.count(F.lit(1)).alias("obs_count"), F.sum("valid_pixel_count").alias("valid_pixel_sum"),
            F.avg("ndvi").alias("mean_ndvi"), F.avg("ndwi").alias("mean_ndwi"), F.avg("ndbi").alias("mean_ndbi"),
            F.stddev_samp("ndvi").alias("std_ndvi"), F.min("ndvi").alias("min_ndvi"), F.max("ndvi").alias("max_ndvi"),
            F.sum("w_ndvi").alias("w_sum"))
        return (out.withColumn("weighted_mean_ndvi", F.col("w_sum") / F.col("valid_pixel_sum")).drop("w_sum")
                .orderBy(*keys))

    annual = agg(["region_id", "year"]).persist()
    regional = agg(["region_id"])
    w = Window.partitionBy("region_id").orderBy("year")
    change = annual.select("region_id", "year", *[f"mean_{c}" for c in INDICES])
    change = change.withColumn("prev_year", F.lag("year").over(w))
    for c in INDICES:
        change = change.withColumn(f"prev_{c}", F.lag(f"mean_{c}").over(w))
    cons = (F.col("year") - F.col("prev_year")) == 1
    change = change.select("region_id", "year", *[F.when(cons, F.col(f"mean_{c}") - F.col(f"prev_{c}")).alias(f"delta_mean_{c}") for c in INDICES]).orderBy("region_id", "year")

    for name, d in (("annual_summary", annual), ("regional_summary", regional), ("annual_change", change)):
        target = out_dir / f"{name}.parquet"
        if write_mode == "native":
            d.coalesce(1).write.mode("overwrite").parquet(str(target))
        else:  # documented fallback: collect the (small) result, write with pyarrow
            target.mkdir(parents=True, exist_ok=True)
            d.toPandas().to_parquet(target / "part-0.parquet", index=False)
    annual.unpersist()
    v.unpersist()
    return {"write_mode": write_mode}
