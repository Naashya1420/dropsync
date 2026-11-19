"""Campus field trial analysis (PDF 4.4, IIIT Allahabad). REAL, measured data.

Input (written by the web app's Field Trial logger via POST /api/trial/*):
  data/field/trip_<id>.json   phone GPS points + taps (arrived, customer ready, delivered),
                              hand-recorded actual gate, variant control|sync, called flag
  data/field/gates.json       campus gates surveyed by the team (OSM has none mapped)

Measures:
  gate_inference_accuracy   gate inferred from GPS alone (nearest surveyed gate to the
                            last outside->inside crossing / final outside stop) vs recorded gate
  rider_wait_s              arrived tap -> delivered tap, control vs sync
  call_rate                 share of trips with a rider-customer call, control vs sync
Output: data/eval/field_results.json
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from .config import EVAL_DIR, FIELD_DIR
from .geo import haversine_m
from .stops import clean_pings, detect_stops


def _nearest_gate(lat, lon, gates):
    d = [(haversine_m(lat, lon, g["lat"], g["lon"]), g["name"]) for g in gates]
    return min(d)[1] if d else None


def main():
    trips = [json.loads(p.read_text()) for p in sorted(FIELD_DIR.glob("trip_*.json"))]
    gates = json.loads((FIELD_DIR / "gates.json").read_text()) if (FIELD_DIR / "gates.json").exists() else []
    if not trips:
        res = dict(status="no field trips recorded yet", trips=0, gates=len(gates))
        EVAL_DIR.mkdir(parents=True, exist_ok=True)
        (EVAL_DIR / "field_results.json").write_text(json.dumps(res, indent=2))
        print(res)
        return res
    rows = []
    for t in trips:
        pts = pd.DataFrame(t["points"])
        if pts.empty:
            continue
        pts["trip_id"] = t["trip_id"]
        cl = clean_pings(pts)
        st = detect_stops(cl)
        # GPS-only gate inference: the point where the rider was closest to any surveyed gate
        # before the 'arrived' tap (crossing proxy: campus polygon is large, gates are on it).
        pred = None
        if gates and len(cl):
            before = cl[cl.ts <= (t.get("arrived_ts") or cl.ts.max())]
            best = None
            for r in before.itertuples():
                for g in gates:
                    d = haversine_m(r.lat, r.lon, g["lat"], g["lon"])
                    if best is None or d < best[0]:
                        best = (d, g["name"])
            pred = best[1] if best and best[0] <= 40 else None
        wait = (t["delivered_ts"] - t["arrived_ts"]) if t.get("delivered_ts") and t.get("arrived_ts") else None
        acc = cl.accuracy_m.dropna() if "accuracy_m" in cl else pd.Series(dtype=float)
        rows.append(dict(trip_id=t["trip_id"], variant=t["variant"], actual_gate=t.get("actual_gate"),
                         pred_gate=pred, gate_ok=(pred == t.get("actual_gate")) if t.get("actual_gate") else None,
                         wait_s=wait, called=t.get("called", False), points=len(pts), cleaned=len(cl),
                         stops=len(st), median_accuracy_m=float(acc.median()) if len(acc) else None))
    df = pd.DataFrame(rows)

    def grp(v):
        x = df[df.variant == v]
        return dict(trips=int(len(x)), rider_wait_s_median=float(x.wait_s.median()) if x.wait_s.notna().any() else None,
                    rider_wait_s_mean=float(x.wait_s.mean()) if x.wait_s.notna().any() else None,
                    call_rate=float(x.called.mean()) if len(x) else None)
    res = dict(status="measured", trips=int(len(df)), gates_surveyed=len(gates),
               gate_inference_accuracy=float(df.gate_ok.dropna().mean()) if df.gate_ok.notna().any() else None,
               gps_median_accuracy_m=float(df.median_accuracy_m.median()) if df.median_accuracy_m.notna().any() else None,
               control=grp("control"), sync=grp("sync"))
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "field_results.json").write_text(json.dumps(res, indent=2, default=float))
    print(json.dumps(res, indent=2, default=float))
    return res


if __name__ == "__main__":
    main()
