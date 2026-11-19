"""Choose the study city by MEASURING OpenStreetMap coverage, not by preference.

For each Indian metro we cut an identical 0.30 x 0.30 degree box (about 33 km)
around the city centre out of the Geofabrik India extract and count what the
DropSync profile builder can use:

  sites               named residential / office / mall polygons (the PDF's core
                      destinations) of plausible single-site size (2,500 - 800,000 m^2)
  sites_with_gate     sites with >= 1 mapped gate/entrance within 20 m of the boundary
  sites_multi_gate    sites with >= 2 such gates (gate choice actually matters)
  gates               barrier=gate|lift_gate|entrance nodes, entrance=* nodes
  bldg_levels         buildings with building:levels (floors -> come-down time prior)
  parking             amenity=parking features

Usage: python -m pipeline.city_select   (expects data/raw/extracts/<City>.osm.pbf)
"""
from __future__ import annotations

import json
import math
import sys

import osmium
import shapely.wkb
from shapely.ops import transform as shp_transform
from shapely.strtree import STRtree

from .config import EVAL_DIR, RAW
from .geo import LocalProjection
from .osm_extract import SITE_MAX_M2, SITE_MIN_M2, _site_kind

CITIES = {  # centre of the Nominatim administrative bounding box (lat, lon)
    "Gurugram": (28.4646, 77.0299), "Bengaluru": (12.9881, 77.6220), "Mumbai": (19.0550, 72.8692),
    "Hyderabad": (17.4262, 78.4305), "Pune": (18.5214, 73.8545), "Chennai": (13.0436, 80.2334),
    "Noida": (28.5181, 77.3997), "Delhi": (28.6028, 77.2050), "Kolkata": (22.5331, 88.3506),
    "Ahmedabad": (23.0215, 72.5800),
}
HALF = 0.15
# Core DropSync destinations: gated societies, office parks, malls (PDF 3.1)
DELIVERY_KINDS = {"residential", "office", "mall"}


def bbox_of(city):
    la, lo = CITIES[city]
    return (round(la - HALF, 4), round(lo - HALF, 4), round(la + HALF, 4), round(lo + HALF, 4))


class Counter(osmium.SimpleHandler):
    def __init__(self, proj):
        super().__init__()
        self.wkb = osmium.geom.WKBFactory()
        self.proj = proj
        self.gates = []
        self.sites = []
        self.bldg_levels = 0
        self.parking = 0

    def node(self, n):
        t = n.tags
        if t.get("barrier") in ("gate", "lift_gate", "entrance") or "entrance" in t:
            self.gates.append(self.proj.to_xy(n.location.lon, n.location.lat))
        if t.get("amenity") == "parking":
            self.parking += 1

    def way(self, w):
        t = w.tags
        if "building" in t and "building:levels" in t:
            self.bldg_levels += 1
        if t.get("amenity") == "parking":
            self.parking += 1

    def area(self, a):
        tags = {k: v for k, v in a.tags}
        kind = _site_kind(tags)
        if kind is None or (not tags.get("name") and kind not in ("campus", "hospital")):
            return
        if "building" in tags and kind not in ("residential", "office", "mall"):
            return
        try:
            g = shapely.wkb.loads(self.wkb.create_multipolygon(a), hex=True)
        except Exception:
            return
        gm = shp_transform(lambda x, y, z=None: self.proj.to_xy(x, y), g)
        if SITE_MIN_M2 <= gm.area <= SITE_MAX_M2:
            self.sites.append((gm, kind))


def measure(city: str) -> dict:
    s, w, n, e = bbox_of(city)
    proj = LocalProjection((s + n) / 2, (w + e) / 2)
    h = Counter(proj)
    h.apply_file(str(RAW / "extracts" / f"{city}.osm.pbf"), locations=True, idx="flex_mem")
    from shapely.geometry import Point
    gpts = [Point(p) for p in h.gates]
    tree = STRtree(gpts) if gpts else None
    with1 = with2 = 0
    centroids = []  # (lat, lon, gates_on_boundary)
    delivery = 0
    for poly, kind in h.sites:
        k = len(tree.query(poly.boundary.buffer(20))) if tree is not None else 0
        if kind not in DELIVERY_KINDS:
            continue  # campuses / hospitals are mapped but not the core target (PDF 3.1)
        delivery += 1
        with1 += k >= 1
        with2 += k >= 2
        c = poly.centroid
        lon, lat = proj.to_lonlat(c.x, c.y)
        centroids.append((lat, lon, k))
    return dict(city=city, bbox=[s, w, n, e], sites=delivery, sites_all_kinds=len(h.sites), sites_with_gate=with1, sites_multi_gate=with2,
                gates=len(h.gates), bldg_levels=h.bldg_levels, parking=h.parking, _centroids=centroids)


ZONE_DEG = 0.03   # ~3 km: the delivery zone of one dark store / rider pool
ZONE_STEP = 0.005


def best_zone(row: dict) -> tuple[list[float], dict]:
    """Slide a ZONE_DEG window over the city box; maximise sites with >=2 gates,
    tie-break on sites with >=1 gate."""
    import numpy as np
    s, w, n, e = row["bbox"]
    c = np.array(row["_centroids"]) if row["_centroids"] else np.zeros((0, 3))
    best = None
    for la in np.arange(s, n - ZONE_DEG + 1e-9, ZONE_STEP):
        for lo in np.arange(w, e - ZONE_DEG + 1e-9, ZONE_STEP):
            m = (c[:, 0] >= la) & (c[:, 0] < la + ZONE_DEG) & (c[:, 1] >= lo) & (c[:, 1] < lo + ZONE_DEG)
            sc = (int((c[m, 2] >= 2).sum()), int((c[m, 2] >= 1).sum()), int(m.sum()))
            if best is None or sc > best[0]:
                best = (sc, [round(la, 4), round(lo, 4), round(la + ZONE_DEG, 4), round(lo + ZONE_DEG, 4)])
    sc, bb = best
    return bb, dict(sites_multi_gate=sc[0], sites_with_gate=sc[1], sites=sc[2])


def main():
    cities = sys.argv[1:] or list(CITIES)
    rows = []
    for c in cities:
        r = measure(c)
        print(json.dumps({k: v for k, v in r.items() if not k.startswith("_")}))
        rows.append(r)
    rows.sort(key=lambda r: (-r["sites_multi_gate"], -r["sites_with_gate"]))
    top = rows[0]
    zone, zstats = best_zone(top)
    from .config import StudyArea, save_study
    why = (f"{top['city']} ranked first of {len(rows)} Indian metros on OSM sites with >=2 mapped gates "
           f"({top['sites_multi_gate']}) in an equal 0.30 deg box; zone = 3 km window with the most such sites "
           f"({zstats['sites_multi_gate']} multi-gate, {zstats['sites_with_gate']} gated, {zstats['sites']} sites).")
    save_study(StudyArea(key=top["city"].lower(), city=top["city"], label=f"{top['city']} study zone",
                         bbox=tuple(zone), why=why))
    print(why, zone)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "city_comparison.json").write_text(json.dumps(
        dict(method=__doc__.strip().splitlines()[0], half_box_deg=HALF, source="Geofabrik India extract",
             rows=[{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
             chosen=dict(city=top["city"], zone_bbox=zone, zone_stats=zstats, why=why)), indent=2))


if __name__ == "__main__":
    main()
