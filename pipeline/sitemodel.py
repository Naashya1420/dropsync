"""Site model derived ONLY from OpenStreetMap: polygons, access points, towers.

An *access point* (AP) is a place where a mapped road / service lane / path
crosses a site's boundary. APs within 30 m of each other are merged. An AP is
marked `osm_gate` when a barrier=gate/lift_gate/entrance node lies within 20 m.
These are the candidate rider gates; which one riders actually use is what
DropSync learns from trips.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import LineString, Point, shape
from shapely.ops import nearest_points, transform as shp_transform
from shapely.strtree import STRtree

from .geo import LocalProjection

DRIVABLE = {"primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link",
            "residential", "unclassified", "service", "living_street", "trunk", "trunk_link", "road", "track"}
WALKABLE_EXTRA = {"footway", "path", "pedestrian", "steps", "corridor", "cycleway"}
AP_MERGE_M = 30.0
GATE_SNAP_M = 20.0


@dataclass
class AccessPoint:
    ap_id: str
    x: float
    y: float
    lat: float
    lon: float
    out_node: int
    in_node: int
    drivable: bool
    osm_gate: bool
    gate_osm_id: int | None = None
    gate_name: str | None = None


@dataclass
class Tower:
    tower_id: str
    x: float
    y: float
    lat: float
    lon: float
    levels: float | None
    footprint: object  # shapely polygon (metric)
    entrance_x: float = 0.0
    entrance_y: float = 0.0
    name: str | None = None      # block name / number from OSM, when mapped


@dataclass
class Site:
    site_id: str
    name: str
    kind: str
    area_m2: float
    poly_ll: object       # shapely polygon lon/lat
    poly: object          # shapely polygon metric
    aps: list[AccessPoint] = field(default_factory=list)
    towers: list[Tower] = field(default_factory=list)
    osm_parking: list[tuple[float, float]] = field(default_factory=list)  # metric xy


def _hw(d):
    h = d.get("highway")
    if isinstance(h, list):
        h = h[0]
    return h


class World:
    """Loaded OSM layer for one area."""

    def __init__(self, osm_dir: Path, bbox):
        self.osm_dir = osm_dir
        s, w, n, e = bbox
        self.proj = LocalProjection((s + n) / 2, (w + e) / 2)
        self.G = ox.load_graphml(osm_dir / "graph.graphml")
        for nid, d in self.G.nodes(data=True):
            d["px"], d["py"] = self.proj.to_xy(d["x"], d["y"])
        self.gates = json.loads((osm_dir / "gates.json").read_text())
        for g in self.gates:
            g["px"], g["py"] = self.proj.to_xy(g["lon"], g["lat"])
        self.buildings = json.loads((osm_dir / "buildings.json").read_text())
        self.parking = json.loads((osm_dir / "parking.json").read_text())
        lp = osm_dir / "building_labels.json"
        self.labels = json.loads(lp.read_text()) if lp.exists() else {}
        self._to_m = lambda geom: shp_transform(lambda x, y, z=None: self.proj.to_xy(x, y), geom)
        # drivable + walkable subgraphs (undirected for routing: two-wheelers
        # in Indian cities use service lanes both ways; one-way handling is out of scope)
        Gu = self.G.to_undirected()
        self.drive = Gu.edge_subgraph([(u, v, k) for u, v, k, d in Gu.edges(keys=True, data=True)
                                       if _hw(d) in DRIVABLE]).copy()
        self.walk = Gu
        for u, v, k, d in self.walk.edges(keys=True, data=True):
            if "length" not in d:
                d["length"] = math.dist((self.G.nodes[u]["px"], self.G.nodes[u]["py"]),
                                        (self.G.nodes[v]["px"], self.G.nodes[v]["py"]))
        self._bld_polys = []
        self._bld_meta = []
        for b in self.buildings:
            try:
                p = self._to_m(shape(b["geometry"]))
            except Exception:
                continue
            if p.is_empty:
                continue
            self._bld_polys.append(p)
            self._bld_meta.append(b)
        self._bld_tree = STRtree(self._bld_polys) if self._bld_polys else None
        # KD-tree over walk-graph nodes for fast nearest-node queries
        from sklearn.neighbors import KDTree
        self._walk_ids = np.array(list(self.walk.nodes))
        self._walk_xy = np.array([self.node_xy(n) for n in self._walk_ids])
        self._walk_kd = KDTree(self._walk_xy)
        self._inside_cache: dict = {}
        self.sites: dict[str, Site] = {}
        self._load_sites()

    # ---------- geometry helpers
    def xy(self, lon, lat):
        return self.proj.to_xy(lon, lat)

    def ll(self, x, y):
        lon, lat = self.proj.to_lonlat(x, y)
        return lat, lon

    def node_xy(self, n):
        d = self.G.nodes[n]
        return d["px"], d["py"]

    def buildings_near(self, x, y, r):
        if self._bld_tree is None:
            return []
        idx = self._bld_tree.query(Point(x, y).buffer(r))
        return [(self._bld_polys[i], self._bld_meta[i]) for i in idx]

    def dist_to_building(self, x, y, r=60.0):
        best = None
        for p, _ in self.buildings_near(x, y, r):
            d = p.exterior.distance(Point(x, y)) if not p.contains(Point(x, y)) else 0.0
            best = d if best is None else min(best, d)
        return best if best is not None else float("inf")

    # ---------- sites
    def _load_sites(self):
        raw = json.loads((self.osm_dir / "sites.json").read_text())
        park_pts = [(self.xy(p["lon"], p["lat"])) for p in self.parking]
        for s in raw:
            poly_ll = shape(s["geometry"])
            poly = self._to_m(poly_ll)
            if not poly.is_valid:
                poly = poly.buffer(0)
            site = Site(s["site_id"], s["name"], s["kind"], s["area_m2"], poly_ll, poly)
            site.aps = self._access_points(site)
            site.towers = self._towers(site)
            site.osm_parking = [p for p in park_pts if poly.buffer(40).contains(Point(p))]
            self.sites[site.site_id] = site

    def _access_points(self, site: Site) -> list[AccessPoint]:
        poly = site.poly
        boundary = poly.exterior
        minx, miny, maxx, maxy = poly.buffer(50).bounds
        crossings = []
        for u, v, k, d in self.walk.edges(keys=True, data=True):
            ux, uy = self.node_xy(u)
            vx, vy = self.node_xy(v)
            if not (minx <= ux <= maxx or minx <= vx <= maxx) or not (miny <= uy <= maxy or miny <= vy <= maxy):
                continue
            iu = poly.contains(Point(ux, uy))
            iv = poly.contains(Point(vx, vy))
            if iu == iv:
                continue
            out_n, in_n = (v, u) if iu else (u, v)
            seg = LineString([(ux, uy), (vx, vy)])
            ip = seg.intersection(boundary)
            if ip.is_empty:
                continue
            if ip.geom_type != "Point":
                ip = list(ip.geoms)[0] if hasattr(ip, "geoms") else ip.centroid
            crossings.append((ip.x, ip.y, out_n, in_n, _hw(d) in DRIVABLE))
        # merge crossings within AP_MERGE_M (prefer drivable representative)
        crossings.sort(key=lambda c: not c[4])
        aps: list[AccessPoint] = []
        for x, y, o, i, drv in crossings:
            if any(math.dist((x, y), (a.x, a.y)) < AP_MERGE_M for a in aps):
                for a in aps:
                    if math.dist((x, y), (a.x, a.y)) < AP_MERGE_M and drv and not a.drivable:
                        a.drivable = True
                continue
            lat, lon = self.ll(x, y)
            aps.append(AccessPoint(f"{site.site_id}#ap{len(aps)}", x, y, lat, lon, o, i, drv, False))
        for a in aps:
            best, bd = None, GATE_SNAP_M
            for g in self.gates:
                dd = math.dist((a.x, a.y), (g["px"], g["py"]))
                if dd < bd:
                    best, bd = g, dd
            if best is not None:
                a.osm_gate = True
                a.gate_osm_id = best["osm_id"]
                a.gate_name = best.get("name")
        return aps

    def _towers(self, site: Site) -> list[Tower]:
        out = []
        for p, meta in self.buildings_near(site.poly.centroid.x, site.poly.centroid.y,
                                           math.sqrt(site.area_m2) * 1.5 + 50):
            c = p.centroid
            if not site.poly.contains(c) or p.area < 120:  # skip sheds / guard rooms
                continue
            lat, lon = self.ll(c.x, c.y)
            out.append(Tower(f"{site.site_id}#t{len(out)}", c.x, c.y, lat, lon, meta.get("levels"), p,
                             name=self.block_label(meta.get("osm_id"), site.name)))
        if not out:
            c = site.poly.representative_point()
            lat, lon = self.ll(c.x, c.y)
            out.append(Tower(f"{site.site_id}#t0", c.x, c.y, lat, lon, None, c.buffer(12)))
        # lobby entrance: footprint point nearest to the site's internal path network
        for t in out:
            n = self.nearest_walk_node(t.x, t.y)
            nx_, ny_ = self.node_xy(n)
            ep, _ = nearest_points(t.footprint.exterior, Point(nx_, ny_))
            t.entrance_x, t.entrance_y = ep.x, ep.y
        return out

    def block_label(self, osm_id, site_name=None) -> str | None:
        """'Tower C' / 'B-Wing' / 'No. 12' from OSM tags, when the building is labelled."""
        t = self.labels.get(osm_id or "", {})
        for k in ("name", "building:name", "addr:housename"):
            v = (t.get(k) or "").strip()
            if v and v != site_name:
                return v
        if t.get("addr:housenumber"):
            return f"No. {t['addr:housenumber'].strip()}"
        if t.get("ref"):
            return t["ref"].strip()
        return None

    def inside_route(self, site: "Site", from_node, to_xy):
        """Walking route inside the site (mapped internal paths and roads) from a gate's
        inner node to a block entrance. Returns ([(x, y)...], metres, mapped: bool)."""
        nodes = self.inside_nodes(site)
        key = ("walksub", site.site_id)
        if key not in self._inside_cache:
            self._inside_cache[key] = self.walk.subgraph(nodes)
        sub = self._inside_cache[key]
        if from_node in sub and nodes:
            to = self.nearest_walk_node(*to_xy, within=nodes)
            try:
                path = nx.shortest_path(sub, from_node, to, weight="length")
                pts = self.path_xy(path) + [to_xy]
                return pts, sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)), True
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass
        a = self.node_xy(from_node)
        return [a, to_xy], math.dist(a, to_xy) * 1.3, False

    def nearest_walk_node(self, x, y, within=None):
        if within is None:
            _, i = self._walk_kd.query([[x, y]], k=1)
            return self._walk_ids[i[0][0]].item()
        best, bd = None, float("inf")
        for n in within:
            d = math.dist((x, y), self.node_xy(n))
            if d < bd:
                best, bd = n, d
        return best

    def inside_nodes(self, site: "Site", buffer_m: float = 8.0) -> list:
        """Walk-graph nodes inside (site polygon + buffer); cached per site."""
        key = (site.site_id, buffer_m)
        if key not in self._inside_cache:
            import shapely
            area = site.poly.buffer(buffer_m)
            minx, miny, maxx, maxy = area.bounds
            m = ((self._walk_xy[:, 0] >= minx) & (self._walk_xy[:, 0] <= maxx) &
                 (self._walk_xy[:, 1] >= miny) & (self._walk_xy[:, 1] <= maxy))
            ids, xy = self._walk_ids[m], self._walk_xy[m]
            ins = shapely.contains_xy(area, xy[:, 0], xy[:, 1]) if len(xy) else np.zeros(0, bool)
            self._inside_cache[key] = [i.item() for i in ids[ins]]
        return self._inside_cache[key]

    def road_name_near(self, node, max_m: float = 150.0) -> str | None:
        """Name of the nearest NAMED road reachable from `node` within max_m along the
        network (the service lane at a gate is usually unnamed; the street it opens onto is not)."""
        dist = nx.single_source_dijkstra_path_length(self.walk, node, cutoff=max_m, weight="length")
        for n, _ in sorted(dist.items(), key=lambda kv: kv[1]):
            for _, _, d in self.walk.edges(n, data=True):
                nm = d.get("name")
                if isinstance(nm, list):
                    nm = nm[0]
                if nm and isinstance(nm, str) and nm.lower() != "nan":
                    return nm
        return None

    def site_of_point(self, x, y, tol=40.0) -> str | None:
        p = Point(x, y)
        best, bd = None, tol
        for s in self.sites.values():
            if s.poly.contains(p):
                return s.site_id
            d = s.poly.distance(p)
            if d < bd:
                best, bd = s.site_id, d
        return best

    def path_xy(self, nodes):
        return [self.node_xy(n) for n in nodes]


def site_summary(site: Site, world: World) -> dict:
    return dict(
        site_id=site.site_id, name=site.name, kind=site.kind, area_m2=site.area_m2,
        polygon=[[round(lat, 6), round(lon, 6)] for lon, lat in site.poly_ll.exterior.coords],
        access_points=[dict(ap_id=a.ap_id, lat=round(a.lat, 6), lon=round(a.lon, 6), osm_gate=a.osm_gate,
                            gate_osm_id=a.gate_osm_id, gate_name=a.gate_name, drivable=a.drivable,
                            road=world.road_name_near(a.out_node))
                       for a in site.aps],
        towers=[dict(tower_id=t.tower_id, lat=round(t.lat, 6), lon=round(t.lon, 6), levels=t.levels,
                     entrance=list(world.ll(t.entrance_x, t.entrance_y)), name=t.name,
                     routes=_routes(site, world, t))
                for t in site.towers],
    )


def _routes(site: Site, world: World, t: Tower) -> dict:
    """Walking route from each entrance to this block's entrance, inside the site."""
    out = {}
    for a in site.aps:
        pts, m, mapped = world.inside_route(site, a.in_node, (t.entrance_x, t.entrance_y))
        pts = [(a.x, a.y)] + pts
        if len(pts) > 30:  # keep the payload small
            idx = np.linspace(0, len(pts) - 1, 30).astype(int)
            pts = [pts[i] for i in idx]
        ll = [world.ll(x, y) for x, y in pts]
        out[a.ap_id] = dict(m=round(m + math.dist((a.x, a.y), world.node_xy(a.in_node))), mapped=mapped,
                            path=[[round(la, 6), round(lo, 6)] for la, lo in ll])
    return out
