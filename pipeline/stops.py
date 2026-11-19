"""GPS cleaning and stop detection (PDF section 3.1, 'How noisy GPS becomes a
reliable profile').

Input is a DataFrame of pings with columns:
    trip_id, ts (unix seconds, float), lat, lon, accuracy_m (may be NaN)
The same code runs on real OpenStreetMap public traces, on simulated
delivery trips and on campus field-trial trips.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .geo import haversine_m

# Thresholds. Values are stated in the PDF where it gives them; others are
# documented engineering choices that the evaluation stresses.
MAX_ACCURACY_M = 30.0        # drop fixes whose reported accuracy is worse (indoor / urban canyon)
MAX_SPEED_MPS = 25.0         # 90 km/h: a jump faster than this between fixes is implausible for a 2-wheeler in a city
STOP_SPEED_MPS = 0.6         # "speed near zero"
STOP_MIN_DURATION_S = 60.0   # "for 60 seconds or more" (PDF)
STOP_MAX_RADIUS_M = 25.0     # all fixes of a stop lie within this radius of its centroid


def clean_pings(df: pd.DataFrame) -> pd.DataFrame:
    """Drop poor-accuracy fixes and implausible jumps. Returns a copy sorted by trip/time."""
    df = df.sort_values(["trip_id", "ts"]).reset_index(drop=True)
    if "accuracy_m" in df:
        acc = df["accuracy_m"]
        df = df[acc.isna() | (acc <= MAX_ACCURACY_M)].copy()
    out = []
    for _, g in df.groupby("trip_id", sort=False):
        keep = np.ones(len(g), dtype=bool)
        lat = g["lat"].to_numpy()
        lon = g["lon"].to_numpy()
        ts = g["ts"].to_numpy()
        last = 0
        for i in range(1, len(g)):
            dt = ts[i] - ts[last]
            if dt <= 0:
                keep[i] = False
                continue
            d = haversine_m(lat[last], lon[last], lat[i], lon[i])
            if d / dt > MAX_SPEED_MPS:
                keep[i] = False  # spike: compare the next fix with the last good one
                continue
            last = i
        out.append(g[keep])
    if not out:
        return df.iloc[0:0].copy()
    return pd.concat(out, ignore_index=True)


def detect_stops(df: pd.DataFrame) -> pd.DataFrame:
    """Detect stops: consecutive cleaned fixes that stay within STOP_MAX_RADIUS_M
    of their running centroid with low speed for at least STOP_MIN_DURATION_S.

    Returns one row per stop: trip_id, start_ts, end_ts, duration_s, lat, lon, n.
    """
    rows = []
    for trip_id, g in df.groupby("trip_id", sort=False):
        lat = g["lat"].to_numpy()
        lon = g["lon"].to_numpy()
        ts = g["ts"].to_numpy()
        n = len(g)
        i = 0
        while i < n - 1:
            j = i
            clat, clon = lat[i], lon[i]
            k = 1
            while j + 1 < n:
                # Only the radius test ends a stop: per-step speeds are dominated by GPS
                # jitter at 1-5 s sampling, so they are not used (walking 60 s ~ 72 m
                # already exceeds the radius). Net speed is checked over the window below.
                d_cent = haversine_m(clat, clon, lat[j + 1], lon[j + 1])
                if d_cent > STOP_MAX_RADIUS_M:
                    break
                j += 1
                k += 1
                clat += (lat[j] - clat) / k
                clon += (lon[j] - clon) / k
            dur = ts[j] - ts[i]
            if dur >= STOP_MIN_DURATION_S and j > i:
                # mean speed over the whole window must be near zero
                path = haversine_m(lat[i:j], lon[i:j], lat[i + 1 : j + 1], lon[i + 1 : j + 1]).sum()
                net = haversine_m(lat[i], lon[i], lat[j], lon[j])
                if net / dur <= STOP_SPEED_MPS:
                    rows.append(
                        dict(trip_id=trip_id, start_ts=ts[i], end_ts=ts[j], duration_s=dur,
                             lat=float(np.mean(lat[i : j + 1])), lon=float(np.mean(lon[i : j + 1])),
                             n=j - i + 1, path_m=float(path))
                    )
                    i = j + 1
                    continue
            i += 1
    return pd.DataFrame(rows, columns=["trip_id", "start_ts", "end_ts", "duration_s", "lat", "lon", "n", "path_m"])
