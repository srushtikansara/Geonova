"""Experiment A (PySpark / Spark SQL engine, local mode)."""
import pandas as pd
from pyspark.sql import SparkSession

INDICES = ["ndvi", "ndwi", "ndbi"]


def get_spark(master="local[*]", shuffle_partitions=8, app="geonova"):
    return (SparkSession.builder.master(master).appName(app)
            .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
            .config("spark.sql.ansi.enabled", "false")
            .config("spark.ui.enabled", "false")
            .getOrCreate())


def region_stats_sdf(spark, sdf):
    """Spark SQL version. NaN is converted to null so it is excluded like Pandas."""
    sdf.createOrReplaceTempView("rec")
    cols = []
    for i in INDICES:
        cols += [
            f"avg(CASE WHEN valid AND NOT isnan({i}) THEN {i} END) AS {i}_mean",
            f"stddev_samp(CASE WHEN valid AND NOT isnan({i}) THEN {i} END) AS {i}_sd",
            f"percentile(CASE WHEN valid AND NOT isnan({i}) THEN {i} END, 0.5) AS {i}_median",
            f"sum(CASE WHEN valid AND NOT isnan({i}) AND {i} IS NOT NULL THEN 1 ELSE 0 END) AS {i}_n",
        ]
    q = f"SELECT city, year, count(*) AS total_pixels, {', '.join(cols)} FROM rec GROUP BY city, year ORDER BY city, year"
    return spark.sql(q)


def region_stats(spark, df_or_path):
    """Accepts a Parquet path or a Pandas DataFrame; returns a Pandas DataFrame."""
    sdf = spark.read.parquet(df_or_path) if isinstance(df_or_path, str) else spark.createDataFrame(df_or_path)
    out = region_stats_sdf(spark, sdf).toPandas()
    for i in INDICES:
        out[f"{i}_coverage"] = out[f"{i}_n"] / out["total_pixels"]
        out[f"{i}_n"] = out[f"{i}_n"].astype("int64")
    out["total_pixels"] = out["total_pixels"].astype("int64")
    return out.sort_values(["city", "year"]).reset_index(drop=True)
