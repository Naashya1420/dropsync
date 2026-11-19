"""Download real public GPS traces from the OpenStreetMap API for the study area.

API: GET /api/0.6/trackpoints?bbox=W,S,E,N&page=N  (5000 points per page).
Only points with timestamps (identifiable / trackable traces) are kept; the API
never reveals who uploaded anonymous points and we store no user names.

Output: data/traces/osm_trackpoints.csv  (trip_id, ts, lat, lon, accuracy_m)
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx
import pandas as pd

from .config import TRACES_DIR, USER_AGENT, load_study

NS = "{http://www.topografix.com/GPX/1/0}"
API = "https://api.openstreetmap.org/api/0.6/trackpoints"
# Pages (5000 points each) fetched per ~1 km tile. 15 pages x 9 tiles caps the download at
# ~675k points, far more than the noise calibration needs, in ~15 min.
MAX_PAGES_PER_TILE = 15


def _get(params):
    for attempt in range(3):
        try:
            r = httpx.get(API, params=params, headers={"User-Agent": USER_AGENT}, timeout=120)
            if r.status_code == 200:
                return r
            if r.status_code == 503:  # server-side first-byte timeout: caller splits the tile
                return None
        except httpx.HTTPError:
            pass
        time.sleep(5 * (attempt + 1))
    return None


def _fetch_tile(s, w, n, e, tag, rows, depth=0, max_pages=MAX_PAGES_PER_TILE):
    """Fetch all pages for one tile; on server timeout split into 4 and recurse."""
    seg_no = 0
    tile_rows = []
    for page in range(max_pages):
        r = _get({"bbox": f"{w},{s},{e},{n}", "page": page})
        if r is None:
            if depth >= 3:
                print(f"  tile {tag} page {page}: server timeout, giving up on this tile")
                return
            print(f"  tile {tag}: server timeout, splitting")
            ms, mw = (s + n) / 2, (w + e) / 2
            for k, (a, b, c, d) in enumerate([(s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)]):
                _fetch_tile(a, b, c, d, f"{tag}.{k}", rows, depth + 1, max_pages)
            return
        root = ET.fromstring(r.content)
        n_pts = 0
        for trk in root.iter(f"{NS}trk"):
            for seg in trk.iter(f"{NS}trkseg"):
                seg_no += 1
                for p in seg.iter(f"{NS}trkpt"):
                    n_pts += 1
                    t = p.find(f"{NS}time")
                    if t is None:
                        continue
                    ts = datetime.fromisoformat(t.text.replace("Z", "+00:00")).timestamp()
                    tile_rows.append((f"osm-{tag}-{page}-{seg_no}", ts, float(p.get("lat")), float(p.get("lon"))))
        n_pts += sum(1 for _ in root.iter(f"{NS}wpt"))
        print(f"  tile {tag} page {page}: {n_pts} points")
        if n_pts < 5000:
            break
        time.sleep(1.0)  # be polite to the OSM API
    rows.extend(tile_rows)


def fetch(bbox_swne, grid: int = 3) -> pd.DataFrame:
    s, w, n, e = bbox_swne
    rows: list = []
    dl = (n - s) / grid
    dw = (e - w) / grid
    for i in range(grid):
        for j in range(grid):
            _fetch_tile(s + i * dl, w + j * dw, s + (i + 1) * dl, w + (j + 1) * dw, f"{i}{j}", rows)
    df = pd.DataFrame(rows, columns=["trip_id", "ts", "lat", "lon"])
    # a trace crossing tile borders appears in several tiles: keep each fix once
    df = df.drop_duplicates(subset=["ts", "lat", "lon"]).reset_index(drop=True)
    df["accuracy_m"] = float("nan")  # GPX from OSM carries no accuracy field
    return df


def main():
    st = load_study()
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    df = fetch(st.bbox)
    out = TRACES_DIR / "osm_trackpoints.csv"
    df.to_csv(out, index=False)
    print(f"[traces] {len(df)} timed points in {df.trip_id.nunique()} segments -> {out}")


if __name__ == "__main__":
    main()
