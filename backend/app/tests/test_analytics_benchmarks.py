import csv
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import models as m
from app.db.import_benchmarks import import_csv
from app.services import regions as svc


def _dataset(db, region="pune", name="d1", day=1):
    r = svc.get_orm(db, region)
    d = m.Dataset(name=name, source="s", mission="Sentinel-2", sensor="MSI L2A", acquisition_date=date(2023, 1, day), region_id=r.id)
    db.add(d)
    db.commit()
    return r, d


def _stat(r, d, day, mval, idx="ndvi", **kw):
    base = dict(region_id=r.id, dataset_id=d.id, observation_date=date(2023, 1, day), index_name=idx,
                mean=mval, minimum=mval - 0.1, maximum=mval + 0.1, valid_pixel_count=90, total_pixel_count=100)
    base.update(kw)
    return m.RegionalAnalytic(**base)


def test_analytics_empty(client):
    assert client.get("/api/analytics/summary").json()["available"] is False
    body = client.get("/api/analytics/temporal?index=ndvi").json()
    assert body["available"] is False and body["points"] == []


def test_analytics_summary_and_temporal(client, seeded):
    r, d1 = _dataset(seeded, day=1)
    _, d2 = _dataset(seeded, name="d2", day=11)
    seeded.add_all([_stat(r, d1, 1, 0.2), _stat(r, d2, 11, 0.3)])
    seeded.commit()
    s = client.get("/api/analytics/summary").json()
    assert s["available"] is True and s["regions_analysed"] == 1 and s["scenes_processed"] == 2
    t = client.get("/api/analytics/temporal?index=ndvi&region=pune").json()
    assert t["available"] and [p["value"] for p in t["points"]] == [0.2, 0.3]
    assert t["points"][0]["date"] == "2023-01-01" and t["points"][0]["valid_pixels"] == 90
    assert client.get("/api/analytics/temporal?index=ndvi&region=pune&date_from=2023-01-05").json()["points"][0]["value"] == 0.3
    assert client.get("/api/analytics/temporal?index=ndwi&region=pune").json()["available"] is False
    pune = next(x for x in client.get("/api/regions").json()["items"] if x["id"] == "pune")
    assert pune["analysed"] is True


def test_temporal_errors_and_multi_region(client, seeded):
    assert client.get("/api/analytics/temporal?index=bad").status_code == 422
    assert client.get("/api/analytics/temporal?region=atlantis").status_code == 404
    assert client.get("/api/analytics/temporal?date_from=2024-01-01&date_to=2023-01-01").status_code == 422
    r1, d1 = _dataset(seeded, "pune")
    r2, d2 = _dataset(seeded, "surat", name="d2")
    seeded.add_all([_stat(r1, d1, 1, 0.2), _stat(r2, d2, 1, 0.4)])
    seeded.commit()
    t = client.get("/api/analytics/temporal?index=ndvi").json()
    assert t["available"] is False and "Select a region" in t["reason"]


def test_analytics_constraints(db):
    seeded = db
    from app.db.seed import seed_regions
    seed_regions(seeded)
    r, d = _dataset(seeded)
    for bad in (dict(valid_pixel_count=-1), dict(total_pixel_count=10), dict(minimum=0.9, maximum=0.1), dict(index_name="evi"), dict(mean=5.0)):
        seeded.add(_stat(r, d, 1, 0.2, **bad))
        with pytest.raises(IntegrityError):
            seeded.commit()
        seeded.rollback()
    seeded.add(_stat(r, d, 1, 0.2))
    seeded.commit()
    seeded.add(_stat(r, d, 1, 0.3))  # duplicate observation
    with pytest.raises(IntegrityError):
        seeded.commit()
    seeded.rollback()


def test_benchmarks_empty(client):
    b = client.get("/api/benchmarks").json()
    assert b["count"] == 0 and b["items"] == [] and "No benchmarks" in b["note"]
    assert client.get("/api/benchmarks/1").status_code == 404
    assert client.get("/api/benchmarks/runs/1").status_code == 404


def test_import_measured_benchmarks(client, db, tmp_path):
    # Values below are TEST FIXTURE numbers for exercising the importer, not measurements.
    p = tmp_path / "bench.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["engine", "master", "records", "data", "runs", "mean_s", "sd_s", "min_s", "peak_driver_rss_mb"])
        w.writerow(["pandas", "local[*]", 1000, "synthetic", 3, 0.5, 0.01, 0.49, 100])
        w.writerow(["spark", "local[*]", 1000, "synthetic", 3, 0.25, 0.01, 0.24, 110])
    assert import_csv(db, str(p)) == 2
    items = client.get("/api/benchmarks").json()["items"]
    assert [i["engine"] for i in items] == ["pandas", "spark"]
    sp = items[1]
    assert sp["speedup"] == pytest.approx(2.0) and sp["throughput"] == pytest.approx(4000.0)
    assert items[0]["speedup"] is None  # baseline has no speedup
    assert sp["records"] == 1000 and sp["data"] == "synthetic"
    assert client.get(f"/api/benchmarks/runs/{sp['id']}").json()["framework"] == "spark"


def test_benchmark_constraints(db):
    for bad in (dict(row_count=0), dict(framework="dask"), dict(duration_s=-1), dict(speedup=0), dict(data_kind="made-up")):
        kw = dict(framework="pandas", workload="w", row_count=10)
        kw.update(bad)
        db.add(m.BenchmarkRun(**kw))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_regional_summary_values_and_empty_state(client, seeded):
    assert client.get("/api/analytics/regional").json() == {"available": False, "items": [], "includes_synthetic": False,
                                                           "reason": "No regional results exist for this selection."}
    r, d1 = _dataset(seeded, day=1)
    _, d2 = _dataset(seeded, name="d2", day=11)
    seeded.add_all([_stat(r, d1, 1, 0.2, valid_pixel_count=50), _stat(r, d2, 11, 0.5, valid_pixel_count=80)])
    seeded.commit()
    b = client.get("/api/analytics/regional?region=pune").json()
    assert b["available"] and len(b["items"]) == 1
    i = b["items"][0]
    assert (i["region"], i["index"], i["observations"]) == ("pune", "ndvi", 2)
    assert i["first_date"] == "2023-01-01" and i["last_date"] == "2023-01-11"
    assert i["latest_mean"] == 0.5 and i["latest_valid_pixels"] == 80 and i["latest_coverage"] == pytest.approx(0.8)
    assert i["change_first_to_last"] == pytest.approx(0.3) and i["synthetic_fixture"] is False
    assert client.get("/api/analytics/regional?region=atlantis").status_code == 404
    assert client.get("/api/analytics/regional?region=surat").json()["available"] is False


def test_regional_hides_synthetic_fixtures_unless_requested(client, seeded):
    r, d = _dataset(seeded)
    d.extra = {"data_kind": "synthetic_test_fixture"}
    seeded.add(_stat(r, d, 1, 0.4))
    seeded.commit()
    assert client.get("/api/analytics/regional").json()["available"] is False
    assert client.get("/api/analytics/summary").json()["available"] is False
    b = client.get("/api/analytics/regional?include_synthetic=true").json()
    assert b["available"] and b["includes_synthetic"] and b["items"][0]["synthetic_fixture"] is True
    assert client.get("/api/analytics/summary?include_synthetic=true").json()["available"] is True
