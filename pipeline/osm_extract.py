"""Extract the real OpenStreetMap layer for one area from a local .osm.pbf
(Geofabrik India extract -> per-city extract made by pipeline.extract_cities).

Produces in <out_dir>/:
  area.osm.pbf     the study box (osmium extract, strategy 'smart')
  sites.json       named delivery destinations (societies, office parks, malls, campuses)
  gates.json       barrier=gate|lift_gate|entrance and entrance=* nodes
  parking.json     amenity=parking features (centroids)
  buildings.json   building footprints (with building:levels where tagged)
  graph.graphml    road + service + path network (osmnx, unsimplified so gate nodes survive)
  meta.json        counts, source file, OSM timestamp, licence

Usage:  python -m pipeline.osm_extract            (study city, from data/study_area.json)
        python -m pipeline.osm_extract --campus   (IIIT Allahabad field-trial area)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import osmium
import osmnx as ox
import shapely.wkb
from shapely.geometry import mapping
from shapely.ops import transform as shp_transform

from .config import CAMPUS, OSM_DIR, RAW, load_study
from .geo import LocalProjection

SITE_MIN_M2 = 2_500       # smaller polygons are single plots, not sites with gates
SITE_MAX_M2 = 800_000     # larger ones are whole sectors / villages, not one site
NOT_ROADS = {"proposed", "construction", "abandoned", "platform", "raceway", "bus_stop", "elevator",
             "rest_area", "services", "razed", "planned", "disused"}


def osmium_cmd(args: list[str], mounts: list[Path]) -> None:
    """Run osmium-tool natively if installed, else through the dropsync-osmium docker image."""
    if shutil.which("osmium"):
        subprocess.run(["osmium", *args], check=True)
        return
    vol = []
    for m in {p.resolve() for p in mounts}:
        vol += ["-v", f"{m}:{m}:Z"]
    subprocess.run(["docker", "run", "--rm", *vol, "dropsync-osmium", *args], check=True)


def _site_kind(tags: dict) -> str | None:
    lu = tags.get("landuse")
    am = tags.get("amenity")
    b = tags.get("building")
    if am in ("university", "college", "school"):
        return "campus"
    if am == "hospital":
        return "hospital"
    if tags.get("shop") == "mall" or (b == "retail" and "name" in tags):
        return "mall"
    if lu == "residential":
        return "residential"
    if lu in ("commercial", "office") or b in ("office", "commercial"):
        return "office"
    if lu == "retail":
        return "mall"
    if b in ("apartments", "residential"):
        return "residential"
    return None


def _levels(v):
    try:
        return float(str(v).split(";")[0]) if v is not None else None
    except ValueError:
        return None


class _Collector(osmium.SimpleHandler):
    def __init__(self, proj: LocalProjection):
        super().__init__()
        self.proj = proj
        self.wkb = osmium.geom.WKBFactory()
        self.gates, self.parking, self.buildings, self.sites = {}, [], [], []

    def node(self, n):
        t = n.tags
        if t.get("barrier") in ("gate", "lift_gate", "entrance") or "entrance" in t:
            self.gates[n.id] = dict(osm_id=n.id, lat=n.location.lat, lon=n.location.lon,
                                    kind=t.get("barrier") or "entrance", entrance=t.get("entrance"),
                                    name=t.get("name"), access=t.get("access"),
                                    motor_vehicle=t.get("motor_vehicle"), foot=t.get("foot"))
        if t.get("amenity") == "parking":
            self.parking.append(dict(osm_id=f"node/{n.id}", lat=n.location.lat, lon=n.location.lon,
                                     parking=t.get("parking"), access=t.get("access")))

    def area(self, a):
        tags = {k: v for k, v in a.tags}
        is_bld = "building" in tags
        is_park = tags.get("amenity") == "parking"
        kind = _site_kind(tags)
        named_site = kind is not None and (tags.get("name") or kind in ("campus", "hospital"))
        if not (is_bld or is_park or named_site):
            return
        try:
            g = shapely.wkb.loads(self.wkb.create_multipolygon(a), hex=True)
        except Exception:
            return
        if g.is_empty:
            return
        if not g.is_valid:
            g = g.buffer(0)
        poly = max(g.geoms, key=lambda p: p.area) if g.geom_type == "MultiPolygon" else g
        oid = f"{'way' if a.from_way() else 'relation'}/{a.orig_id()}"
        if is_park:
            c = poly.centroid
            self.parking.append(dict(osm_id=oid, lat=c.y, lon=c.x, parking=tags.get("parking"),
                                     access=tags.get("access")))
        if is_bld:
            self.buildings.append(dict(osm_id=oid, levels=_levels(tags.get("building:levels")),
                                       building=tags.get("building"), name=tags.get("name"),
                                       geometry=mapping(poly)))
        if named_site:
            gm = shp_transform(lambda x, y, z=None: self.proj.to_xy(x, y), poly)
            if SITE_MIN_M2 <= gm.area <= SITE_MAX_M2:
                self.sites.append(dict(
                    site_id=oid, name=tags.get("name") or kind.title(), kind=kind, area_m2=round(gm.area),
                    tags={k: v for k, v in tags.items() if k in (
                        "landuse", "amenity", "building", "shop", "addr:street", "addr:city", "addr:postcode",
                        "operator", "access", "barrier")},
                    geometry=mapping(poly)))


class _PoiCollector(osmium.SimpleHandler):
    """Named food outlets (pickup points for the rider app's pickup leg)."""
    KINDS = {"restaurant", "fast_food", "cafe"}

    def __init__(self):
        super().__init__()
        self.pois = []
        self.wkb = osmium.geom.WKBFactory()

    def _add(self, oid, tags, lat, lon):
        self.pois.append(dict(osm_id=oid, name=tags.get("name"), kind=tags.get("amenity"),
                              cuisine=tags.get("cuisine"), lat=lat, lon=lon))

    def node(self, n):
        if n.tags.get("amenity") in self.KINDS and n.tags.get("name"):
            self._add(f"node/{n.id}", n.tags, n.location.lat, n.location.lon)

    def area(self, a):
        if a.tags.get("amenity") in self.KINDS and a.tags.get("name"):
            try:
                g = shapely.wkb.loads(self.wkb.create_multipolygon(a), hex=True)
            except Exception:
                return
            c = g.centroid
            self._add(f"{'way' if a.from_way() else 'relation'}/{a.orig_id()}", a.tags, c.y, c.x)


def extract_pois(area_pbf: Path, out_dir: Path) -> int:
    h = _PoiCollector()
    h.apply_file(str(area_pbf), locations=True, idx="flex_mem")
    (out_dir / "restaurants.json").write_text(json.dumps(h.pois))
    print(f"[osm] restaurants/cafes/fast food with names: {len(h.pois)}")
    return len(h.pois)


def extract(src_pbf: Path, area_bbox, out_dir: Path, label: str) -> dict:
    s, w, n, e = area_bbox
    out_dir.mkdir(parents=True, exist_ok=True)
    area_pbf = out_dir / "area.osm.pbf"
    print(f"[osm] {label}: cutting {w},{s},{e},{n} from {src_pbf.name}")
    osmium_cmd(["extract", "--overwrite", "-s", "smart", "-b", f"{w},{s},{e},{n}", str(src_pbf.resolve()),
                "-o", str(area_pbf.resolve())], [src_pbf.parent, out_dir])

    proj = LocalProjection((s + n) / 2, (w + e) / 2)
    h = _Collector(proj)
    h.apply_file(str(area_pbf), locations=True, idx="flex_mem")

    # drop sites fully inside a larger site (towers inside a society, blocks inside a campus)
    from shapely.geometry import shape
    shapes = [shape(si["geometry"]) for si in h.sites]
    order = sorted(range(len(h.sites)), key=lambda i: -h.sites[i]["area_m2"])
    keep_idx = []
    for i in order:
        if not any(shapes[j].buffer(1e-5).contains(shapes[i]) for j in keep_idx):
            keep_idx.append(i)
    sites = [h.sites[i] for i in sorted(keep_idx)]
    n_pois = extract_pois(area_pbf, out_dir)
    print(f"[osm] sites {len(sites)} (of {len(h.sites)} candidates), gates {len(h.gates)}, "
          f"parking {len(h.parking)}, buildings {len(h.buildings)}")
    (out_dir / "sites.json").write_text(json.dumps(sites))
    (out_dir / "gates.json").write_text(json.dumps(list(h.gates.values())))
    (out_dir / "parking.json").write_text(json.dumps(h.parking))
    (out_dir / "buildings.json").write_text(json.dumps(h.buildings))

    # road / path network
    hw_osm = out_dir / "highways.osm"
    osmium_cmd(["tags-filter", "--overwrite", str(area_pbf.resolve()), "w/highway", "-o", str(hw_osm.resolve())],
               [out_dir])
    ox.settings.useful_tags_node = list(set(ox.settings.useful_tags_node) | {"barrier", "entrance", "access"})
    ox.settings.useful_tags_way = list(set(ox.settings.useful_tags_way) | {"service", "access", "barrier"})
    G = ox.graph_from_xml(hw_osm, simplify=False, retain_all=True)
    bad = [(u, v, k) for u, v, k, d in G.edges(keys=True, data=True)
           if (d.get("highway")[0] if isinstance(d.get("highway"), list) else d.get("highway")) in NOT_ROADS]
    G.remove_edges_from(bad)
    G.remove_nodes_from([x for x in list(G.nodes) if G.degree(x) == 0])
    # clip to bbox (smart strategy may pull complete ways far outside the box)
    G.remove_nodes_from([x for x, d in G.nodes(data=True)
                         if not (s - 0.005 <= d["y"] <= n + 0.005 and w - 0.005 <= d["x"] <= e + 0.005)])
    ox.save_graphml(G, out_dir / "graph.graphml")
    hw_osm.unlink()
    india = sorted(RAW.glob("india-*.osm.pbf"))
    osm_ts = None
    if india:
        r = osmium.io.Reader(str(india[-1]), osmium.osm.osm_entity_bits.NOTHING)
        osm_ts = r.header().get("osmosis_replication_timestamp")
        r.close()
    meta = dict(label=label, bbox=[s, w, n, e], source=f"{india[-1].name if india else '?'} -> {src_pbf.name}",
                osm_timestamp=osm_ts,
                license="© OpenStreetMap contributors, ODbL 1.0 (via Geofabrik)",
                sites=len(sites), gates=len(h.gates), parking=len(h.parking), buildings=len(h.buildings),
                restaurants=n_pois,
                buildings_with_levels=sum(1 for b in h.buildings if b["levels"]),
                graph_nodes=G.number_of_nodes(), graph_edges=G.number_of_edges())
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[osm] graph nodes {G.number_of_nodes()}, edges {G.number_of_edges()}")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--campus", action="store_true", help="extract the IIIT Allahabad field-trial area")
    ap.add_argument("--pois-only", action="store_true", help="only (re)extract restaurants from area.osm.pbf")
    a = ap.parse_args()
    if a.pois_only:
        d = OSM_DIR / ("campus" if a.campus else "city")
        n = extract_pois(d / "area.osm.pbf", d)
        meta = json.loads((d / "meta.json").read_text())
        meta["restaurants"] = n
        (d / "meta.json").write_text(json.dumps(meta, indent=2))
        return
    if a.campus:
        res = extract(RAW / "extracts" / "campus_iiita.osm.pbf", CAMPUS.bbox, OSM_DIR / "campus", CAMPUS.label)
    else:
        st = load_study()
        res = extract(RAW / "extracts" / f"{st.city}.osm.pbf", st.bbox, OSM_DIR / "city", st.label)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
