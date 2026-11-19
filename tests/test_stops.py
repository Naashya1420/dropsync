import numpy as np
import pandas as pd

from pipeline.geo import offset_m
from pipeline.stops import clean_pings, detect_stops

LAT0, LON0 = 28.45, 77.05


def _trip(segments, trip_id="t", dt=5.0, noise=0.0, seed=0):
    """segments: list of (dx_m, dy_m, seconds) moves; (0,0,s) = stand still."""
    rng = np.random.default_rng(seed)
    rows, t, x, y = [], 0.0, 0.0, 0.0
    for dx, dy, sec in segments:
        n = max(1, int(sec / dt))
        for i in range(n):
            x += dx / n
            y += dy / n
            t += dt
            lat, lon = offset_m(LAT0, LON0, x + rng.normal(0, noise), y + rng.normal(0, noise))
            rows.append((trip_id, t, lat, lon, 5.0))
    return pd.DataFrame(rows, columns=["trip_id", "ts", "lat", "lon", "accuracy_m"])


def test_stop_detected_when_still_for_two_minutes():
    df = _trip([(500, 0, 100), (0, 0, 120), (300, 0, 60)], noise=3.0)
    stops = detect_stops(clean_pings(df))
    assert len(stops) == 1
    assert 100 <= stops.iloc[0].duration_s <= 130


def test_short_pause_is_not_a_stop():
    df = _trip([(500, 0, 100), (0, 0, 40), (300, 0, 60)], noise=3.0)
    assert len(detect_stops(clean_pings(df))) == 0


def test_spike_and_poor_accuracy_fixes_removed():
    df = _trip([(0, 0, 100)])
    spike = df.iloc[5].copy()
    spike["lat"] += 0.01  # ~1.1 km jump in 5 s
    spike["ts"] += 0.5
    bad = df.iloc[6].copy()
    bad["accuracy_m"] = 120.0
    bad["ts"] += 0.5
    dirty = pd.concat([df, spike.to_frame().T, bad.to_frame().T]).astype({"ts": float, "lat": float, "lon": float})
    cleaned = clean_pings(dirty)
    assert len(cleaned) == len(df)
