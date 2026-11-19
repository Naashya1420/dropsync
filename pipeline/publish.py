"""Nightly-batch output: build the production profiles from the full history and
publish them for the real-time service and the apps.

Writes data/out/:
  profiles.json   one profile per site (what the apps may show)
  sites.json      site geometry for maps: polygon, OSM access points, towers (+entrance, floors)
  meta.json       study area, data provenance, counts, build time

Then, if DATABASE_URL is set, loads the PostGIS store (pipeline.db).
Usage: python -m pipeline.publish
"""
from __future__ import annotations

import json
import os
import time

import pandas as pd

from .config import EVAL_DIR, OSM_DIR, OUT_DIR, SIM_DIR, load_study
from .profile_builder import build_profiles
from .simulate import load_world
from .sitemodel import site_summary


def main():
    t0 = time.time()
    st = load_study()
    world = load_world()
    trips = pd.read_parquet(SIM_DIR / "trips.parquet")
    pings = pd.read_parquet(SIM_DIR / "pings.parquet")
    profiles = build_profiles(world, trips, pings)
    sites = {}
    for sid in profiles:
        sites[sid] = site_summary(world.sites[sid], world)
    # sites present in OSM but without delivery history: map only (cold start)
    for sid, s in world.sites.items():
        if sid not in sites:
            sites[sid] = dict(site_summary(s, world), cold_start=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "profiles.json").write_text(json.dumps(profiles, default=float))
    (OUT_DIR / "sites.json").write_text(json.dumps(sites))
    osm_meta = json.loads((OSM_DIR / "city" / "meta.json").read_text())
    noise = json.loads((EVAL_DIR / "noise_calibration.json").read_text())
    meta = dict(
        study=dict(city=st.city, label=st.label, bbox=st.bbox, why=st.why),
        built_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        sources=[
            dict(name="OpenStreetMap (Geofabrik India extract)", kind="real", detail=osm_meta),
            dict(name="OpenStreetMap public GPS traces", kind="real",
                 detail=dict(points=noise["raw_points"], segments=noise["segments"], use="GPS noise calibration")),
            dict(name="Simulated delivery history", kind="simulated",
                 detail=dict(trips=int(len(trips)), pings=int(len(pings)), sites=int(trips.site_id.nunique()),
                             days=int(trips.day.max() + 1))),
        ],
        counts=dict(sites_with_profile=len(profiles), sites_total=len(sites),
                    shown_gate_hint=sum(p["show_gate_hint"] for p in profiles.values()),
                    shown_sync=sum(p["show_sync"] for p in profiles.values())),
    )
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2, default=float))
    print(f"[publish] {len(profiles)} profiles, {len(sites)} sites in {time.time()-t0:.0f}s")
    if os.environ.get("DATABASE_URL"):
        from .db import load
        load(os.environ["DATABASE_URL"], profiles, sites)


if __name__ == "__main__":
    main()
