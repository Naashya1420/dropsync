"""Simulated delivery history on the REAL OpenStreetMap layer.

Why simulate: no public Indian last-mile dataset has delivery GPS + events (see
README, "Data"). We therefore generate a delivery history whose *map* is real
(OSM roads, site boundaries, gates, buildings, floor counts, parking) and whose
*GPS error* is measured from real Indian OSM traces (pipeline/noise.py), while
behaviour (which gate guards allow, handover rules, customer reaction) is an
explicit, documented assumption (config.SimAssumptions). Because the ground
truth is known, profile accuracy can be measured exactly; the campus field
trial supplies measured Indian numbers.

Nothing in the profile builder reads the ground-truth columns.

Outputs (data/sim/):
  truth_sites.json  hidden per-site truth (rider gate by time of day, rule
                    changes, handover type, parking point, tower floors)
  trips.parquet     one row per order: events the delivery app already emits
                    (assigned, arrived, delivered), pin, plus truth_* columns
  pings.parquet     rider GPS fixes: trip_id, ts, lat, lon, accuracy_m
"""
from __future__ import annotations

import json
import math
import zlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

from .config import EVAL_DIR, OSM_DIR, SIM, SIM_DIR, SimAssumptions, load_study
from .sitemodel import Site, World

IST = timezone(timedelta(hours=5, minutes=30))
BASE = datetime(2026, 8, 1, tzinfo=IST)  # day 0 of the simulated history
HANDOVER_TYPES = ("gate", "lobby", "doorstep")


def is_night(hour: int) -> bool:
    return hour >= 23 or hour < 6


class Timeline:
    """Piecewise-linear rider motion: list of (t0, t1, x0, y0, x1, y1, mode)."""

    def __init__(self, t: float, x: float, y: float):
        self.segs: list[tuple] = []
        self.t, self.x, self.y = t, x, y

    def move_to(self, x, y, speed_mps, mode):
        d = math.dist((self.x, self.y), (x, y))
        if d < 0.01:
            return
        dt = d / speed_mps
        self.segs.append((self.t, self.t + dt, self.x, self.y, x, y, mode))
        self.t += dt
        self.x, self.y = x, y

    def follow(self, pts, speed_mps, mode):
        for x, y in pts:
            self.move_to(x, y, speed_mps, mode)

    def wait(self, seconds, mode="stop"):
        if seconds <= 0:
            return
        self.segs.append((self.t, self.t + seconds, self.x, self.y, self.x, self.y, mode))
        self.t += seconds

    def position(self, t):
        """Position at time t. Calls must be made with non-decreasing t (pings are)."""
        i = getattr(self, "_ptr", 0)
        if i >= len(self.segs) or (i and self.segs[i][0] > t):
            i = 0
        while i < len(self.segs):
            t0, t1, x0, y0, x1, y1, mode = self.segs[i]
            if t0 <= t <= t1:
                self._ptr = i
                f = 0 if t1 == t0 else (t - t0) / (t1 - t0)
                return x0 + f * (x1 - x0), y0 + f * (y1 - y0), mode
            i += 1
        return self.x, self.y, self.segs[-1][6] if self.segs else "stop"


class Simulator:
    def __init__(self, world: World, sim: SimAssumptions, noise: dict):
        self.w = world
        self.sim = sim
        self.noise = noise
        self.sigma = noise["stationary"]["sigma_per_axis_m"]
        st = noise["stationary"]
        self.rho1 = max(0.0, min(0.999, st.get("rho_per_s") if st.get("rho_per_s") is not None else st["lag1_autocorr"]))
        self.spike = noise["spike_rate"]
        self.rng = np.random.default_rng(sim.seed)
        self.drive_nodes = set(world.drive.nodes)
        # connected component id per drive node: routes only exist within one component
        self.comp = {}
        for ci, comp in enumerate(nx.connected_components(world.drive)):
            for n in comp:
                self.comp[n] = ci
        self._sub_cache: dict = {}
        self._outside_cache: dict = {}

    # ------------------------------------------------------------------ truth
    def outside_graph(self, site: Site):
        """Drive network without the site's interior (riders reach and switch gates from outside)."""
        if site.site_id not in self._outside_cache:
            # drop every road SEGMENT that touches the site's interior (a node filter alone
            # lets segments cut across concave corners of the wall)
            inner = site.poly.buffer(-3)
            minx, miny, maxx, maxy = site.poly.buffer(10).bounds
            keep = []
            for u, v, k in self.w.drive.edges(keys=True):
                (x1, y1), (x2, y2) = self.w.node_xy(u), self.w.node_xy(v)
                if max(x1, x2) < minx or min(x1, x2) > maxx or max(y1, y2) < miny or min(y1, y2) > maxy:
                    keep.append((u, v, k))
                    continue
                if not inner.intersects(LineString([(x1, y1), (x2, y2)])):
                    keep.append((u, v, k))
            G = self.w.drive.edge_subgraph(keep)
            comp = {}
            for ci, cc in enumerate(nx.connected_components(G)):
                for n in cc:
                    comp[n] = ci
            self._outside_cache[site.site_id] = (G, comp)
        return self._outside_cache[site.site_id]

    def candidates(self, site: Site):
        """Drivable access points that can all be reached from each other WITHOUT driving
        through the site (the outside road component holding most of the site's gates)."""
        G, comp = self.outside_graph(site)
        c = [a for a in site.aps if a.drivable and a.out_node in comp]
        if not c:
            return []
        from collections import Counter
        best = Counter(comp[a.out_node] for a in c).most_common(1)[0][0]
        return [a for a in c if comp[a.out_node] == best]

    def eligible(self, site: Site) -> bool:
        return bool(self.candidates(site))

    def make_truth(self, site: Site) -> dict:
        rng = np.random.default_rng(zlib.crc32(f"{self.sim.seed}:{site.site_id}".encode()))
        cand = self.candidates(site)
        wts = np.array([2.0 if a.osm_gate else 1.0 for a in cand])
        day_gate = cand[rng.choice(len(cand), p=wts / wts.sum())]
        others = [a for a in cand if a.ap_id != day_gate.ap_id]
        night_gate = day_gate
        if others and rng.random() < self.sim.night_gate_change_prob:
            night_gate = others[rng.integers(len(others))]
        changed_gate = None
        if others and rng.random() < self.sim.rule_change_prob:
            changed_gate = others[rng.integers(len(others))]
        mix = self.sim.residential_handover_mix if site.kind == "residential" else self.sim.commercial_handover_mix
        htype = HANDOVER_TYPES[rng.choice(3, p=np.array(mix) / sum(mix))]
        park_inside = htype != "gate" and rng.random() < 0.5
        lo, hi = (self.sim.floors_default_residential if site.kind == "residential"
                  else self.sim.floors_default_commercial)
        towers = {}
        for t in site.towers:
            lv = t.levels if t.levels else float(rng.integers(lo, hi + 1))
            towers[t.tower_id] = dict(levels=lv, levels_from_osm=bool(t.levels))
        return dict(site_id=site.site_id, day_gate=day_gate.ap_id, night_gate=night_gate.ap_id,
                    changed_gate=changed_gate.ap_id if changed_gate else None,
                    change_day=self.sim.rule_change_day if changed_gate else None,
                    handover_type=htype, park_inside=bool(park_inside), towers=towers,
                    n_candidate_gates=len(cand))

    @staticmethod
    def true_gate(truth: dict, day: int, hour: int) -> str:
        if is_night(hour):
            g = truth["night_gate"]
            if truth["changed_gate"] and day >= truth["change_day"] and truth["night_gate"] == truth["day_gate"]:
                g = truth["changed_gate"]
            return g
        if truth["changed_gate"] and day >= truth["change_day"]:
            return truth["changed_gate"]
        return truth["day_gate"]

    # ----------------------------------------------------------------- geometry
    def _ap(self, site: Site, ap_id: str):
        return next(a for a in site.aps if a.ap_id == ap_id)

    def _parking_xy(self, site: Site, ap, inside: bool, rng):
        if inside:
            # real OSM parking inside the site near the gate, if mapped
            near = [p for p in site.osm_parking if site.poly.contains(Point(p)) and math.dist(p, (ap.x, ap.y)) < 120]
            if near:
                return min(near, key=lambda p: math.dist(p, (ap.x, ap.y)))
            ix, iy = self.w.node_xy(ap.in_node)
            vx, vy = ix - ap.x, iy - ap.y
            d = math.hypot(vx, vy) or 1.0
            step = min(30.0, max(10.0, d))
            px, py = ap.x + vx / d * step, ap.y + vy / d * step
            if not site.poly.contains(Point(px, py)):
                px, py = ix, iy
            return px, py
        ox_, oy_ = self.w.node_xy(ap.out_node)
        vx, vy = ox_ - ap.x, oy_ - ap.y
        d = math.hypot(vx, vy) or 1.0
        step = min(12.0, d)
        # 4 m to the side of the lane
        return ap.x + vx / d * step - vy / d * 4.0, ap.y + vy / d * step + vx / d * 4.0

    def _inside_path(self, site: Site, a_node, b_xy, graph):
        """Shortest path inside the site from node a to the node nearest b_xy."""
        key = (site.site_id, id(graph))
        if key not in self._sub_cache:
            nodes = [n for n in self.w.inside_nodes(site) if n in graph]
            self._sub_cache[key] = (nodes, graph.subgraph(nodes))
        nodes, sub = self._sub_cache[key]
        if a_node not in sub:
            sub = graph.subgraph(nodes + [a_node])
        b = self.w.nearest_walk_node(*b_xy, within=nodes or [a_node])
        try:
            p = nx.shortest_path(sub, a_node, b, weight="length")
            return self.w.path_xy(p) + [b_xy]
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return [b_xy]

    # ------------------------------------------------------------------- trips
    def simulate(self, site_ids=None, orders_override: int | None = None, workers: int = 1):
        """Simulate every eligible site. Sites are independent (each has its own
        deterministic RNG), so they run in parallel with `workers` processes."""
        sites = [s for s in self.w.sites.values() if self.eligible(s)]
        if site_ids is not None:
            keep = set(site_ids)
            sites = [s for s in sites if s.site_id in keep]
        ids = [s.site_id for s in sites]
        if workers > 1 and len(ids) > 1:
            import multiprocessing as mp
            global _WORKER_SIM
            _WORKER_SIM = self
            with mp.get_context("fork").Pool(workers) as pool:
                res = pool.starmap(_site_worker, [(sid, orders_override) for sid in ids], chunksize=1)
        else:
            res = [self.simulate_site(sid, orders_override) for sid in ids]
        truths = {r[0]["site_id"]: r[0] for r in res}
        trips = pd.concat([r[1] for r in res], ignore_index=True)
        pings = pd.concat([r[2] for r in res], ignore_index=True)
        return truths, trips, pings

    def simulate_site(self, sid: str, orders_override: int | None = None):
        sim = self.sim
        site = self.w.sites[sid]
        rng = np.random.default_rng(zlib.crc32(f"orders:{sim.seed}:{sid}".encode()))
        truth = self.make_truth(site)
        hours = np.array(list(sim.hour_weights.keys()))
        hw = np.array(list(sim.hour_weights.values()), dtype=float)
        hw /= hw.sum()
        cand = self.candidates(site)
        # Riders reach a gate (and reroute between gates) on roads OUTSIDE the site: a rider
        # refused at one gate cannot cut through the society's internal roads.
        outside, _ = self.outside_graph(site)
        dij = {a.ap_id: nx.single_source_dijkstra(outside, a.out_node, cutoff=sim.approach_radius_m * 1.6,
                                                  weight="length") for a in cand}
        dist0 = dij[truth["day_gate"]][0]
        b30 = site.poly.buffer(30)
        starts = [n for n, d in dist0.items()
                  if 0.7 * sim.approach_radius_m <= d <= sim.approach_radius_m
                  and not b30.contains(Point(self.w.node_xy(n)))]
        if not starts:
            starts = [n for n, d in dist0.items() if d >= 0.3 * sim.approach_radius_m] or list(dist0)
        pre = dict(cand=cand, dij=dij, starts=starts, outside=outside)
        lo, hi = sim.orders_per_site_range
        n = orders_override or int(np.clip(rng.pareto(1.2) * lo + lo, lo, hi))
        orders = sorted((int(rng.integers(0, sim.days)), int(rng.choice(hours, p=hw)), float(rng.uniform(0, 60)))
                        for _ in range(n))
        rows, frames = [], []
        safe = sid.replace("/", "_")
        for k, (day, hour, minute) in enumerate(orders):
            t0 = (BASE + timedelta(days=day, hours=hour, minutes=minute)).timestamp()
            rid = f"r{int(rng.integers(sim.riders))}"
            row, pings = self._one_trip(f"{safe}-{k}", site, truth, pre, rid, day, hour, t0, rng)
            rows.append(row)
            frames.append(pings)
        return truth, pd.DataFrame(rows), pd.concat(frames, ignore_index=True)

    def _one_trip(self, trip_id, site, truth, pre, rid, day, hour, t0, rng):
        sim = self.sim
        true_ap_id = self.true_gate(truth, day, hour)
        true_ap = self._ap(site, true_ap_id)
        htype = truth["handover_type"]
        # destination tower (bigger buildings get more orders)
        towers = site.towers
        tw = np.array([max(t.footprint.area, 50) * (truth["towers"][t.tower_id]["levels"]) for t in towers])
        tower = towers[rng.choice(len(towers), p=tw / tw.sum())]
        levels = truth["towers"][tower.tower_id]["levels"]
        # customer's saved pin: usually the tower, sometimes wrong (site centroid / other tower)
        pin_wrong = rng.random() < sim.pin_wrong_prob
        if pin_wrong:
            c = site.poly.centroid if rng.random() < 0.5 or len(towers) == 1 else None
            pin_xy = (c.x, c.y) if c is not None else (lambda o: (o.x, o.y))(
                towers[(towers.index(tower) + 1) % len(towers)])
        else:
            pin_xy = (tower.x, tower.y)

        start = pre["starts"][int(rng.integers(len(pre["starts"])))]
        # Does this rider already know the building? (explicit assumption, see config)
        new_to_site = rng.random() < sim.new_to_site_share
        visits = 0 if new_to_site else int(rng.integers(1, 30))
        if not new_to_site:
            chosen = true_ap_id
            chooser = "memory"
            # after a permanent gate change, experienced riders keep using the old gate for a while
            if (truth["changed_gate"] and truth["change_day"] <= day < truth["change_day"] + sim.stale_memory_days
                    and not is_night(hour) and rng.random() < sim.stale_memory_prob):
                chosen = truth["day_gate"]
                chooser = "stale_memory"
        else:
            # navigation behaviour: gate that minimises road distance + straight line to pin
            best, bd = None, float("inf")
            for a in pre["cand"]:
                d = pre["dij"][a.ap_id][0].get(start)
                if d is None:
                    continue
                tot = d + math.dist((a.x, a.y), pin_xy)
                if tot < bd:
                    best, bd = a.ap_id, tot
            chosen = best or true_ap_id
            chooser = "navigation"
        if truth.get("force_choice"):
            # scenario hook (learning-stages demo): this rider heads for a given gate
            chosen, chooser = truth["force_choice"], "forced"
        speed_factor = float(rng.uniform(0.75, 1.25))
        v_road = sim.rider_speed_kmh_road / 3.6 * speed_factor
        v_in = sim.rider_speed_kmh_inside / 3.6 * speed_factor
        v_walk = sim.walk_speed_mps * float(rng.uniform(0.85, 1.15))

        tl = Timeline(t0, *self.w.node_xy(start))

        def drive_to_gate(ap_id, from_node):
            dist, paths = pre["dij"][ap_id]
            p = paths.get(from_node)
            if p is None:
                p = nx.shortest_path(pre["outside"], from_node, self._ap(site, ap_id).out_node, weight="length")
            else:
                p = list(reversed(p))
            tl.follow(self.w.path_xy(p), v_road, "drive")
            a = self._ap(site, ap_id)
            # approach the gate itself (stop ~4 m before the boundary)
            ox_, oy_ = self.w.node_xy(a.out_node)
            vx, vy = a.x - ox_, a.y - oy_
            d = math.hypot(vx, vy) or 1.0
            tl.move_to(a.x - vx / d * min(4.0, d), a.y - vy / d * min(4.0, d), v_in, "drive")
            return a

        wrong_gate = chosen != true_ap_id
        admitted = False
        penalty_start = None
        entry_ap = true_ap
        if wrong_gate:
            penalty_start = tl.t
            a = drive_to_gate(chosen, start)
            tl.wait(float(rng.uniform(*sim.wrong_gate_argue_s)), "stop")
            admitted = rng.random() < sim.wrong_gate_admitted_prob
            if admitted:
                entry_ap = a
            else:
                # reroute along roads to the correct gate
                try:
                    p = nx.shortest_path(pre["outside"], a.out_node, true_ap.out_node, weight="length")
                    tl.follow(self.w.path_xy(p), v_road, "drive")
                except nx.NetworkXNoPath:
                    tl.move_to(*self.w.node_xy(true_ap.out_node), v_road, "drive")
                drive_to_gate(true_ap_id, true_ap.out_node)
        else:
            drive_to_gate(true_ap_id, start)
        # wrong-gate penalty = extra time vs going straight to the right gate
        direct_s = None
        if wrong_gate:
            d_direct = pre["dij"][true_ap_id][0].get(start)
            direct_s = (d_direct or 0) / v_road
        tl.wait(float(rng.uniform(5, 30)), "stop")  # guard check / entry log

        inside_park = truth["park_inside"] and htype != "gate"
        park_xy = self._parking_xy(site, entry_ap, inside_park, rng)
        if inside_park:
            tl.move_to(entry_ap.x, entry_ap.y, v_in, "drive")
            if entry_ap.in_node in self.drive_nodes:
                for x, y in self._inside_path(site, entry_ap.in_node, park_xy, self.w.drive)[-6:]:
                    tl.move_to(x, y, v_in, "drive")
            else:
                tl.move_to(*park_xy, v_in, "drive")
        else:
            tl.move_to(*park_xy, v_in, "drive")
        arrived_t = tl.t
        drive_end_t = tl.t
        tl.wait(float(rng.uniform(20, 45)), "stop")  # park, take the bag

        lift_wait = float(rng.uniform(*sim.lift_wait_s))
        ride = levels * sim.floor_height_m / sim.lift_speed_mps
        ready = float(rng.uniform(*sim.customer_ready_s))
        call = float(rng.uniform(*sim.call_connect_s))
        ent = (tower.entrance_x, tower.entrance_y)
        if htype == "gate":
            hp = (entry_ap.x, entry_ap.y)
            ox_, oy_ = self.w.node_xy(entry_ap.out_node)
            vx, vy = entry_ap.x - ox_, entry_ap.y - oy_
            d = math.hypot(vx, vy) or 1.0
            hp = (entry_ap.x - vx / d * 2.0, entry_ap.y - vy / d * 2.0)  # stand at the gate, outside
            tl.move_to(*hp, v_walk, "walk")
            walk_cust = (math.dist(ent, (entry_ap.x, entry_ap.y)) * 1.25) / sim.walk_speed_mps
        else:
            if not inside_park:
                tl.move_to(entry_ap.x, entry_ap.y, v_walk, "walk")
                nodes_from = entry_ap.in_node
            else:
                nodes_from = self.w.nearest_walk_node(*park_xy)
            path = self._inside_path(site, nodes_from, ent, self.w.walk)
            tl.follow(path, v_walk, "walk")
            # lobby: wait just outside the entrance
            cx, cy = tower.x, tower.y
            vx, vy = ent[0] - cx, ent[1] - cy
            d = math.hypot(vx, vy) or 1.0
            hp = (ent[0] + vx / d * 3.0, ent[1] + vy / d * 3.0)
            tl.move_to(*hp, v_walk, "walk")
            walk_cust = 10.0 / sim.walk_speed_mps
        rider_at_hp = tl.t
        cust_lead = ready + lift_wait + ride + walk_cust
        if htype == "doorstep":
            tl.wait(lift_wait + ride + float(rng.uniform(*sim.doorstep_handover_s)), "indoor")
        else:
            tl.wait(call + cust_lead + 10.0, "stop")
        delivered_t = tl.t
        tl.wait(20.0, "stop" if htype != "doorstep" else "indoor")

        # boundary event: first time within 30 m of the site
        boundary_t = None
        b30 = site.poly.buffer(30)
        for seg in tl.segs:
            if b30.contains(Point(seg[4], seg[5])):
                boundary_t = seg[0] if b30.contains(Point(seg[2], seg[3])) else seg[1]
                break
        boundary_t = boundary_t or arrived_t

        pings = self._pings(trip_id, tl, rng, site)
        wrong_penalty = 0.0
        if wrong_gate:
            # time lost: actual time to reach parking minus direct-route time to the right gate
            wrong_penalty = max(0.0, (drive_end_t - penalty_start) - (direct_s or 0) -
                                math.dist((true_ap.x, true_ap.y), park_xy) / v_in)
        pin_lat, pin_lon = self.w.ll(*pin_xy)
        hp_lat, hp_lon = self.w.ll(*hp)
        row = dict(
            trip_id=trip_id, site_id=site.site_id, rider_id=rid, day=day, hour=hour,
            assigned_ts=t0, arrived_ts=arrived_t + float(rng.normal(0, 8)), delivered_ts=delivered_t,
            pin_lat=pin_lat, pin_lon=pin_lon, tower_id=tower.tower_id,
            # ---- ground truth (never read by the profile builder) ----
            truth_gate=true_ap_id, truth_entry_ap=entry_ap.ap_id, truth_chosen=chosen, truth_chooser=chooser,
            truth_wrong_gate=wrong_gate, truth_admitted=admitted, truth_wrong_penalty_s=wrong_penalty,
            truth_handover_type=htype, truth_levels=levels, truth_park_inside=inside_park,
            truth_park_lat=self.w.ll(*park_xy)[0], truth_park_lon=self.w.ll(*park_xy)[1],
            truth_hp_lat=hp_lat, truth_hp_lon=hp_lon,
            truth_boundary_ts=boundary_t, truth_drive_end_ts=drive_end_t, truth_rider_at_hp_ts=rider_at_hp,
            truth_cust_lead_s=cust_lead, truth_call_s=call, truth_speed_factor=speed_factor,
            truth_rider_visits=visits, truth_pin_wrong=pin_wrong,
            truth_notif_ignored=bool(rng.random() < sim.notif_ignore_prob),
        )
        return row, pings

    def _pings(self, trip_id, tl: Timeline, rng, site):
        sim = self.sim
        t = tl.segs[0][0]
        end = tl.t
        rows = []
        ex = ey = 0.0
        last_t = None
        while t <= end:
            x, y, mode = tl.position(t)
            dt = 1.0 if last_t is None else t - last_t
            r = self.rho1 ** dt
            # urban canyon: next to a tall building the error grows
            sig = self.sigma
            if mode in ("stop", "walk") and self.w.dist_to_building(x, y, 25) < 8:
                sig *= 1.8
            ex = r * ex + math.sqrt(max(0.0, 1 - r * r)) * rng.normal(0, sig)
            ey = r * ey + math.sqrt(max(0.0, 1 - r * r)) * rng.normal(0, sig)
            last_t = t
            if mode == "indoor":
                if rng.random() < 0.6:
                    t += sim.ping_interval_s * float(rng.uniform(0.9, 1.1))
                    continue  # no fix indoors
                acc = float(rng.uniform(40, 150))
                px, py = x + rng.normal(0, acc / 2), y + rng.normal(0, acc / 2)
            else:
                px, py = x + ex, y + ey
                acc = max(4.0, math.hypot(ex, ey) * float(rng.uniform(1.0, 2.0)) + 3.0)
                if rng.random() < self.spike:
                    ang = rng.uniform(0, 2 * math.pi)
                    dd = rng.uniform(80, 400)
                    px, py = px + dd * math.cos(ang), py + dd * math.sin(ang)
            lat, lon = self.w.ll(px, py)
            rows.append((trip_id, t, lat, lon, round(acc, 1)))
            t += sim.ping_interval_s * float(rng.uniform(0.9, 1.1))
        return pd.DataFrame(rows, columns=["trip_id", "ts", "lat", "lon", "accuracy_m"])


_WORKER_SIM: "Simulator | None" = None


def _site_worker(sid, orders_override):
    return _WORKER_SIM.simulate_site(sid, orders_override)


def load_world() -> World:
    st = load_study()
    return World(OSM_DIR / "city", st.bbox)


def load_noise() -> dict:
    return json.loads((EVAL_DIR / "noise_calibration.json").read_text())


def run(sim: SimAssumptions = SIM, out_dir=SIM_DIR, world: World | None = None, noise: dict | None = None,
        site_ids=None, orders_override=None, noise_scale: float = 1.0, workers: int = 1):
    world = world or load_world()
    noise = noise or load_noise()
    if noise_scale != 1.0:
        noise = json.loads(json.dumps(noise))
        noise["stationary"]["sigma_per_axis_m"] *= noise_scale
    S = Simulator(world, sim, noise)
    truths, trips, pings = S.simulate(site_ids=site_ids, orders_override=orders_override, workers=workers)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "truth_sites.json").write_text(json.dumps(truths, indent=1))
    trips.to_parquet(out_dir / "trips.parquet", index=False)
    pings.to_parquet(out_dir / "pings.parquet", index=False)
    return truths, trips, pings


if __name__ == "__main__":
    import time
    t = time.time()
    import os
    truths, trips, pings = run(workers=int(os.environ.get("DROPSYNC_WORKERS", "12")))
    print(f"[sim] sites {len(truths)}, trips {len(trips)}, pings {len(pings)} in {time.time()-t:.0f}s")
    print(trips[["truth_chooser", "truth_wrong_gate"]].value_counts())
    print(trips["truth_handover_type"].value_counts())
