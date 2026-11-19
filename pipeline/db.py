"""PostGIS building-profile store (PDF 4.1 'Building profile store').

Tables
  sites(site_id PK, name, kind, area_m2, geom geometry(Polygon,4326))
  access_points(ap_id PK, site_id FK, osm_gate, gate_osm_id, geom geometry(Point,4326))
  profiles(site_id PK FK, confidence, handover_type, show_gate_hint, show_sync,
           gate_ap_id, gate_geom, night_gate_ap_id, parking_geom, handover_median_s,
           handover_p80_s, come_down_lead_s, trips, profile jsonb, updated_at)
Usage: DATABASE_URL=postgresql://dropsync:dropsync@localhost:5433/dropsync python -m pipeline.db
"""
from __future__ import annotations

import json
import os

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS sites (
  site_id text PRIMARY KEY, name text, kind text, area_m2 double precision,
  geom geometry(Polygon, 4326));
CREATE INDEX IF NOT EXISTS sites_geom_idx ON sites USING gist (geom);
CREATE TABLE IF NOT EXISTS access_points (
  ap_id text PRIMARY KEY, site_id text REFERENCES sites(site_id) ON DELETE CASCADE,
  osm_gate boolean, gate_osm_id bigint, geom geometry(Point, 4326));
CREATE TABLE IF NOT EXISTS profiles (
  site_id text PRIMARY KEY REFERENCES sites(site_id) ON DELETE CASCADE,
  confidence text, handover_type text, show_gate_hint boolean, show_sync boolean,
  gate_ap_id text, gate_geom geometry(Point, 4326), night_gate_ap_id text,
  parking_geom geometry(Point, 4326), handover_median_s double precision, handover_p80_s double precision,
  come_down_lead_s double precision, trips integer, profile jsonb, updated_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS sync_feedback (
  id bigserial PRIMARY KEY, site_id text, order_id text, reply text, lead_observed_s double precision,
  helped boolean, created_at timestamptz DEFAULT now());
"""


def _pt(lat, lon):
    return f"SRID=4326;POINT({lon} {lat})"


def load(url: str, profiles: dict, sites: dict) -> None:
    import psycopg
    with psycopg.connect(url) as con, con.cursor() as cur:
        cur.execute(SCHEMA)
        cur.execute("TRUNCATE sites CASCADE")
        for sid, s in sites.items():
            ring = ", ".join(f"{lon} {lat}" for lat, lon in s["polygon"])
            cur.execute("INSERT INTO sites VALUES (%s,%s,%s,%s, ST_MakeValid(ST_GeomFromEWKT(%s)))",
                        (sid, s["name"], s["kind"], s["area_m2"], f"SRID=4326;POLYGON(({ring}))"))
            for a in s["access_points"]:
                cur.execute("INSERT INTO access_points VALUES (%s,%s,%s,%s, ST_GeomFromEWKT(%s))",
                            (a["ap_id"], sid, a["osm_gate"], a["gate_osm_id"], _pt(a["lat"], a["lon"])))
        for sid, p in profiles.items():
            g = p.get("gate_day") or {}
            pk = p.get("parking") or {}
            ho = p.get("handover_time_s") or {}
            cur.execute(
                """INSERT INTO profiles (site_id, confidence, handover_type, show_gate_hint, show_sync, gate_ap_id,
                   gate_geom, night_gate_ap_id, parking_geom, handover_median_s, handover_p80_s, come_down_lead_s,
                   trips, profile) VALUES (%s,%s,%s,%s,%s,%s, ST_GeomFromEWKT(%s), %s, ST_GeomFromEWKT(%s),
                   %s,%s,%s,%s,%s)""",
                (sid, p["confidence"], (p.get("handover") or {}).get("type"), p["show_gate_hint"], p["show_sync"],
                 g.get("ap_id"), _pt(g["lat"], g["lon"]) if g else None,
                 (p.get("gate_night") or {}).get("ap_id"), _pt(pk["lat"], pk["lon"]) if pk else None,
                 ho.get("median"), ho.get("p80"), p.get("come_down_lead_s"), p["trips"],
                 json.dumps(p, default=float)))
        con.commit()
        cur.execute("SELECT count(*) FROM profiles")
        print(f"[db] loaded {cur.fetchone()[0]} profiles into PostGIS")


def fetch_profiles(url: str) -> dict:
    import psycopg
    with psycopg.connect(url) as con, con.cursor() as cur:
        cur.execute("SELECT site_id, profile FROM profiles")
        return {sid: prof for sid, prof in cur.fetchall()}


if __name__ == "__main__":
    from .config import OUT_DIR
    load(os.environ["DATABASE_URL"], json.loads((OUT_DIR / "profiles.json").read_text()),
         json.loads((OUT_DIR / "sites.json").read_text()))
