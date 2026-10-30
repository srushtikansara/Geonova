"""Run Experiments A and D on a records Parquet and write CSVs to outputs/."""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from geonova import analysis_pandas as ap, analysis_spark as asp, compare  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--records", default="data/records.parquet")
p.add_argument("--outdir", default="outputs")
a = p.parse_args()
os.makedirs(a.outdir, exist_ok=True)
df = pd.read_parquet(a.records)
A = ap.region_stats(df)
A.to_csv(f"{a.outdir}/regional_stats_pandas.csv", index=False)
spark = asp.get_spark()
B = asp.region_stats(spark, a.records)
B.to_csv(f"{a.outdir}/regional_stats_spark.csv", index=False)
rep = compare.compare(A, B)
print("keys match:", rep["keys_match"])
if rep["keys_match"]:
    print(rep["table"].to_string(index=False))
    print("PASS" if rep["pass"] else "FAIL")
    rep["table"].to_csv(f"{a.outdir}/consistency.csv", index=False)
