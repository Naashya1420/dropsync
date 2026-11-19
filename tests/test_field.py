"""Field-trial analysis on a synthetic recorded trip (temp folder only)."""
import json

import numpy as np

from pipeline import field
from pipeline.geo import offset_m

LAT0, LON0 = 25.4300, 81.7700  # IIIT Allahabad area


def _trip(tid, variant, gate_xy, wait_s, called):
    pts, t = [], 1_000_000.0
    # approach the gate from 300 m away, then stand still near it
    for i in range(60):
        lat, lon = offset_m(LAT0, LON0, gate_xy[0] - 300 + i * 5, gate_xy[1])
        pts.append(dict(ts=t, lat=lat, lon=lon, accuracy_m=6.0))
        t += 5
    arrived = t
    for _ in range(int(wait_s / 5)):
        lat, lon = offset_m(LAT0, LON0, gate_xy[0] + np.random.normal(0, 2), gate_xy[1] + np.random.normal(0, 2))
        pts.append(dict(ts=t, lat=lat, lon=lon, accuracy_m=6.0))
        t += 5
    return dict(trip_id=tid, variant=variant, destination="H1", actual_gate="Main gate", handover_type="gate",
                arrived_ts=arrived, customer_ready_ts=t - 5, delivered_ts=t, called=called, points=pts)


def test_field_analysis(tmp_path, monkeypatch):
    np.random.seed(0)
    monkeypatch.setattr(field, "FIELD_DIR", tmp_path / "field")
    monkeypatch.setattr(field, "EVAL_DIR", tmp_path / "eval")
    (tmp_path / "field").mkdir()
    g_main = offset_m(LAT0, LON0, 0, 0)
    g_back = offset_m(LAT0, LON0, 0, 400)
    (tmp_path / "field" / "gates.json").write_text(json.dumps([
        dict(name="Main gate", lat=g_main[0], lon=g_main[1]), dict(name="Back gate", lat=g_back[0], lon=g_back[1])]))
    for i in range(3):
        (tmp_path / "field" / f"trip_c{i}.json").write_text(json.dumps(_trip(f"c{i}", "control", (0, 0), 240, True)))
        (tmp_path / "field" / f"trip_s{i}.json").write_text(json.dumps(_trip(f"s{i}", "sync", (0, 0), 30, False)))
    res = field.main()
    assert res["trips"] == 6
    assert res["gate_inference_accuracy"] == 1.0
    assert res["control"]["rider_wait_s_median"] > res["sync"]["rider_wait_s_median"]
    assert res["control"]["call_rate"] == 1.0 and res["sync"]["call_rate"] == 0.0
