"""Measure GPS error characteristics from REAL Indian OSM public traces.

Three measurements, all from data/traces/osm_trackpoints.csv:
  1. Stationary jitter: inside detected stops, distance of each fix to the stop
     centroid. Gives the per-axis sigma of a 2-D Gaussian (Rayleigh fit) and the
     lag-1 autocorrelation of the error (GPS error is temporally correlated).
  2. Spike rate: share of fixes removed by the implausible-speed filter.
  3. Cross-track residual: for moving fixes (2-25 m/s), distance to the nearest
     mapped road/path centreline. This bounds GPS + map error from above.
Also reports the sampling interval distribution.

Output: data/eval/noise_calibration.json, used by the simulator.
"""
from __future__ import annotations

import json
import math

import numpy as np
import osmnx as ox
import pandas as pd
from shapely.strtree import STRtree

from .config import EVAL_DIR, OSM_DIR, TRACES_DIR, load_study
from .geo import LocalProjection, haversine_m
from .stops import clean_pings, detect_stops


def calibrate() -> dict:
    st = load_study()
    df = pd.read_csv(TRACES_DIR / "osm_trackpoints.csv")
    n_raw = len(df)
    cleaned = clean_pings(df)
    spike_rate = 1 - len(cleaned) / max(n_raw, 1)

    dts = cleaned.groupby("trip_id")["ts"].diff().dropna()
    dts = dts[dts > 0]

    # 1. stationary jitter
    stops = detect_stops(cleaned)
    devs, ac_pairs = [], []
    by_trip = {k: g for k, g in cleaned.groupby("trip_id")}
    for s in stops.itertuples():
        g = by_trip[s.trip_id]
        w = g[(g.ts >= s.start_ts) & (g.ts <= s.end_ts)]
        if len(w) < 10:
            continue
        lat0, lon0 = w.lat.mean(), w.lon.mean()
        dy = (w.lat.to_numpy() - lat0) * 111_320
        dx = (w.lon.to_numpy() - lon0) * 111_320 * math.cos(math.radians(lat0))
        devs.extend(np.hypot(dx, dy).tolist())
        if len(dx) > 3:
            ac_pairs.append((dx[:-1], dx[1:]))
            ac_pairs.append((dy[:-1], dy[1:]))
    devs = np.array(devs)
    if len(devs):
        # Rayleigh MLE for per-axis sigma
        sigma = float(np.sqrt(np.mean(devs ** 2) / 2))
    else:
        sigma = float("nan")
    if ac_pairs:
        a = np.concatenate([p[0] for p in ac_pairs])
        b = np.concatenate([p[1] for p in ac_pairs])
        rho = float(np.corrcoef(a, b)[0, 1])
    else:
        rho = float("nan")

    # 3. cross-track residual to mapped roads
    G = ox.load_graphml(OSM_DIR / "city" / "graph.graphml")
    proj = LocalProjection((st.bbox[0] + st.bbox[2]) / 2, (st.bbox[1] + st.bbox[3]) / 2)
    from shapely.geometry import LineString, Point
    lines = []
    for u, v, d in G.edges(data=True):
        x1, y1 = proj.to_xy(G.nodes[u]["x"], G.nodes[u]["y"])
        x2, y2 = proj.to_xy(G.nodes[v]["x"], G.nodes[v]["y"])
        if (x1, y1) != (x2, y2):
            lines.append(LineString([(x1, y1), (x2, y2)]))
    tree = STRtree(lines)
    resid = []
    c = cleaned.copy()
    c["dt"] = c.groupby("trip_id")["ts"].diff()
    c["step"] = haversine_m(c.lat, c.lon, c.groupby("trip_id")["lat"].shift(), c.groupby("trip_id")["lon"].shift())
    c["v"] = c.step / c.dt
    mv = c[(c.v > 2) & (c.v < 25)]
    s0, w0, n0, e0 = st.bbox
    mv = mv[(mv.lat > s0) & (mv.lat < n0) & (mv.lon > w0) & (mv.lon < e0)]
    xs, ys = proj.to_xy(mv.lon.to_numpy(), mv.lat.to_numpy())
    pts = [Point(x, y) for x, y in zip(xs, ys)]
    if pts:
        idx = tree.nearest(pts)
        resid = np.array([pts[i].distance(lines[j]) for i, j in enumerate(idx)])
    else:
        resid = np.array([])

    def q(a, p):
        return float(np.quantile(a, p)) if len(a) else None

    out = dict(
        source="OpenStreetMap public GPS traces (real, India), study area " + st.label,
        raw_points=int(n_raw), cleaned_points=int(len(cleaned)),
        segments=int(df.trip_id.nunique()),
        years=sorted(pd.to_datetime(df.ts, unit="s").dt.year.unique().tolist()),
        spike_rate=round(spike_rate, 4),
        sampling_interval_s=dict(median=q(dts, .5), p90=q(dts, .9), share_le_5s=float((dts <= 5).mean()) if len(dts) else None),
        stops_detected=int(len(stops)),
        stationary=dict(n_fixes=int(len(devs)), radial_median_m=q(devs, .5), radial_p95_m=q(devs, .95),
                        sigma_per_axis_m=round(sigma, 2), lag1_autocorr=round(rho, 3),
                        # lag-1 autocorrelation measured at the traces' median sampling interval,
                        # converted to a per-second value for the simulator: rho_s = rho ** (1 / dt)
                        rho_per_s=round(float(max(rho, 0.0) ** (1.0 / q(dts, .5))), 4) if len(dts) else None),
        cross_track=dict(n_fixes=int(len(resid)), median_m=q(resid, .5), p90_m=q(resid, .9), p95_m=q(resid, .95)),
    )
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "noise_calibration.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    print(json.dumps(calibrate(), indent=2))
