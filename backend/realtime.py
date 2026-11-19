"""Real-time service logic (PDF 3.2 + 4.1 'Real-time service').

On assignment: fetch profile. On every rider location: compute ETA to the
learned handover point; when ETA <= the building's come-down lead time, push the
customer sync ONCE. Customer replies with one tap; the rider card shows it. On
delivery: log the outcome (feeds lead-time refinement and fair-lateness).

For the live demo the rider's GPS is replayed along a real OSM route at a
configurable speed-up; in production the same `on_location` would be fed by the
delivery app's location stream.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from dataclasses import dataclass, field

import networkx as nx

from pipeline.config import SIM

NOMINAL_SPEED_MPS = 18.0 / 3.6     # same nominal 2-wheeler speed the ETA model assumes
WALK_MPS = 1.2
GUARD_CHECK_S = 15.0
PARK_S = 25.0
FLOOR_H_M = 3.0
LIFT_MPS = 1.0


def hav(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


class Router:
    """Shortest paths on the OSM drive network (undirected, as in the simulator)."""

    DRIVABLE = {"primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link",
                "residential", "unclassified", "service", "living_street", "trunk", "trunk_link", "road", "track"}

    def __init__(self, graphml_path):
        G = self._load(graphml_path).to_undirected()

        def hw(d):
            h = d.get("highway")
            return h[0] if isinstance(h, list) else h
        self.G = G.edge_subgraph([(u, v, k) for u, v, k, d in G.edges(keys=True, data=True)
                                  if hw(d) in self.DRIVABLE]).copy()
        self.nodes = list(self.G.nodes)
        self.coords = {n: (self.G.nodes[n]["y"], self.G.nodes[n]["x"]) for n in self.nodes}

    @staticmethod
    def _load(path):
        """Load the OSMnx-written graphml. Uses osmnx when installed; otherwise plain
        networkx + the few type conversions the router needs (keeps the deployed
        server small: no geopandas/shapely stack)."""
        try:
            import osmnx as ox
            return ox.load_graphml(path)
        except ImportError:
            import ast
            G = nx.read_graphml(path, node_type=int, force_multigraph=True)
            for _, d in G.nodes(data=True):
                d["x"], d["y"] = float(d["x"]), float(d["y"])
            for _, _, d in G.edges(data=True):
                d["length"] = float(d.get("length", 0) or 0)
                for k in ("highway", "name"):
                    v = d.get(k)
                    if isinstance(v, str) and v.startswith("["):
                        try:
                            d[k] = ast.literal_eval(v)
                        except (ValueError, SyntaxError):
                            pass
            return G

    def road_name(self, lat, lon, max_m: float = 200.0) -> str | None:
        """Nearest NAMED road along the network from (lat, lon), from OSM edge names."""
        dist = nx.single_source_dijkstra_path_length(self.G, self.nearest(lat, lon), cutoff=max_m, weight="length")
        for n, _ in sorted(dist.items(), key=lambda kv: kv[1]):
            for _, _, d in self.G.edges(n, data=True):
                nm = d.get("name")
                if isinstance(nm, list):
                    nm = nm[0]
                if isinstance(nm, str) and nm and nm.lower() != "nan":
                    return nm
        return None

    def nearest(self, lat, lon):
        return min(self.nodes, key=lambda n: hav(self.coords[n], (lat, lon)))

    def route(self, a, b):
        p = nx.shortest_path(self.G, a, b, weight="length")
        return [self.coords[n] for n in p]

    def start_node_at(self, lat, lon, dist_m, rng):
        dist = nx.single_source_dijkstra_path_length(self.G, self.nearest(lat, lon), cutoff=dist_m * 1.3,
                                                     weight="length")
        cand = [n for n, d in dist.items() if 0.8 * dist_m <= d <= 1.3 * dist_m]
        if not cand:
            cand = sorted(dist, key=dist.get)[-20:]
        return cand[int(rng.integers(len(cand)))]


@dataclass
class Order:
    order_id: str
    site: dict
    profile: dict | None
    tower: dict
    pin: tuple
    new_partner: bool
    speedup: float
    route: list                 # [(lat, lon)] drive path to the gate
    gate: dict                  # learned gate (or what navigation picked if no hint)
    parking: tuple
    handover_point: tuple
    handover_type: str
    lead_s: float | None
    lead_explain: str
    created: float = field(default_factory=time.time)
    sim_t: float = 0.0
    phase: str = "assigned"
    rider: tuple | None = None
    eta_s: float | None = None
    notified_at: float | None = None
    reply: str | None = None
    reply_at: float | None = None
    customer_at_hp_at: float | None = None
    rider_at_hp_at: float | None = None
    boundary_at: float | None = None
    delivered_at: float | None = None
    events: list = field(default_factory=list)
    subscribers: set = field(default_factory=set)
    sync_enabled: bool = True
    fair: dict | None = None
    cust_descent_s: float = 180.0   # simulated customer's true time to reach the handover point
    cust_start_at: float | None = None
    # rider-app mode: pickup leg + stage changes confirmed by the rider (slide buttons)
    manual: bool = False
    pickup: dict | None = None      # real OSM restaurant {name, kind, lat, lon}
    route_pickup: list = field(default_factory=list)
    accepted_at: float | None = None
    reached_pickup_at: float | None = None
    picked_up_at: float | None = None
    arrived_at: float | None = None  # rider's 'Reached drop location' tap (the app's existing event)
    called_at: float | None = None
    calls: int = 0
    helped: bool | None = None
    delivered_wall: float | None = None   # wall-clock time of delivery (for stale-order checks)


def _gate_for(profile, site, hour):
    if profile and profile.get("show_gate_hint"):
        g = profile["gate_day"]
        if profile.get("gate_night") and (hour >= 23 or hour < 6):
            g = profile["gate_night"]
        ap = next((a for a in site["access_points"] if a["ap_id"] == g.get("ap_id")), {})
        return dict(g, source="learned", road=ap.get("road"))
    # no confident hint: the rider goes where navigation takes them (gate nearest the pin)
    return None


def lead_time(profile: dict, tower: dict) -> tuple[float | None, str]:
    """Come-down lead time for this order's tower."""
    if not profile or profile.get("come_down_lead_s") is None:
        return None, "no confident lead time"
    base = float(profile["come_down_lead_s"])
    med = (profile.get("osm_levels") or {}).get("median")
    lv = tower.get("levels")
    if med and lv:
        adj = (lv - med) * FLOOR_H_M / LIFT_MPS
        return max(30.0, base + adj), (f"building median {base:.0f}s, tower has {lv:.0f} floors vs "
                                       f"site median {med:.0f} ({adj:+.0f}s)")
    return base, f"building median {base:.0f}s (learned from {profile['trips']} trips)"


class Hub:
    def __init__(self, router: Router, sites: dict, profiles_getter, feedback_path, restaurants=None):
        self.restaurants = restaurants or []
        self.latest: str | None = None
        self.router = router
        self.sites = sites
        self.get_profile = profiles_getter
        self.orders: dict[str, Order] = {}
        self.feedback_path = feedback_path

    # ------------------------------------------------------------------ create
    def create(self, site_id: str, tower_id: str | None, pin: tuple | None, new_partner: bool,
               speedup: float, start_dist_m: float, hour: int, sync_enabled: bool = True,
               with_pickup: bool = False, manual: bool = False) -> Order:
        import numpy as np
        rng = np.random.default_rng()
        site = self.sites[site_id]
        prof = self.get_profile(site_id)
        towers = site["towers"]
        tower = next((t for t in towers if t["tower_id"] == tower_id), towers[0])
        pin = pin or (tower["lat"], tower["lon"])
        g = _gate_for(prof, site, hour)
        aps = [a for a in site["access_points"] if a.get("drivable", True)] or site["access_points"]
        if g is None:
            ap = min(aps, key=lambda a: hav((a["lat"], a["lon"]), pin))
            g = dict(ap_id=ap["ap_id"], lat=ap["lat"], lon=ap["lon"], osm_gate=ap["osm_gate"],
                     gate_name=ap.get("gate_name"), road=ap.get("road"), source="navigation (no confident profile)")
        htype = ((prof or {}).get("handover") or {}).get("type") or "doorstep"
        if (prof or {}).get("parking"):
            parking = (prof["parking"]["lat"], prof["parking"]["lon"])
        else:
            parking = (g["lat"], g["lon"])
        if htype == "gate":
            hp = (g["lat"], g["lon"])
        else:
            hp = tuple(tower.get("entrance") or (tower["lat"], tower["lon"]))
        lead, why = lead_time(prof, tower)
        # Demo: start far enough away that the nudge fires mid-route (as in production for
        # most orders); if the lead time exceeds the whole trip, it would fire on assignment.
        post = (prof or {}).get("park_to_handover_point_s") or 60.0
        if lead:
            start_dist_m = max(start_dist_m, (lead - post - GUARD_CHECK_S - PARK_S + 90.0) * NOMINAL_SPEED_MPS)
        gate_node = self.router.nearest(g["lat"], g["lon"])
        pickup, route_pickup = None, []
        if with_pickup and self.restaurants:
            # a real restaurant far enough away that the nudge can fire during the drop leg
            want = start_dist_m * 0.75
            cand = [r for r in self.restaurants if want <= hav((r["lat"], r["lon"]), (g["lat"], g["lon"])) <= want * 1.8]
            if not cand:
                cand = sorted(self.restaurants, key=lambda r: -hav((r["lat"], r["lon"]), (g["lat"], g["lon"])))[:15]
            pickup = dict(cand[int(rng.integers(len(cand)))])
            pickup["road"] = self.router.road_name(pickup["lat"], pickup["lon"])
            r_node = self.router.nearest(pickup["lat"], pickup["lon"])
            route = [(pickup["lat"], pickup["lon"])] + self.router.route(r_node, gate_node) + [(g["lat"], g["lon"])]
            r_start = self.router.start_node_at(pickup["lat"], pickup["lon"], 500.0, rng)
            route_pickup = self.router.route(r_start, r_node) + [(pickup["lat"], pickup["lon"])]
        else:
            start = self.router.start_node_at(g["lat"], g["lon"], start_dist_m, rng)
            route = self.router.route(start, gate_node) + [(g["lat"], g["lon"])]
        # The simulated customer's TRUE time to reach the handover point once they start
        # (independent of DropSync's estimate): midpoints of the documented simulation
        # assumptions (config.SimAssumptions) + this tower's floors + walk to the point.
        levels = tower.get("levels") or 10
        walk_m = hav(tuple(tower.get("entrance") or (tower["lat"], tower["lon"])), hp) * 1.25
        cust_descent = (sum(SIM.customer_ready_s) / 2 + sum(SIM.lift_wait_s) / 2
                        + levels * SIM.floor_height_m / SIM.lift_speed_mps + walk_m / SIM.walk_speed_mps)
        o = Order(order_id=uuid.uuid4().hex[:8], site=site, profile=prof, tower=tower, pin=pin,
                  new_partner=new_partner, speedup=speedup, route=route, gate=g, parking=parking,
                  handover_point=hp, handover_type=htype, lead_s=lead, lead_explain=why,
                  sync_enabled=sync_enabled and bool(prof and prof.get("show_sync")),
                  cust_descent_s=cust_descent, manual=manual, pickup=pickup, route_pickup=route_pickup)
        o.rider = route_pickup[0] if route_pickup else route[0]
        self.orders[o.order_id] = o
        self.latest = o.order_id
        if pickup:
            self._event(o, "offered", f"Order offered: pick up at {pickup['name']}, drop at {site['name']}")
        else:
            self._event(o, "assigned", f"Rider assigned, {self._route_len(route):.0f} m from {self._gate_label(g)}")
        return o

    @staticmethod
    def _gate_label(g):
        if g.get("gate_name"):
            return g["gate_name"]
        kind = "gate" if g.get("osm_gate") else "entrance"
        return f"the {kind} on {g['road']}" if g.get("road") else f"the {kind}"

    @staticmethod
    def _route_len(route):
        return sum(hav(route[i], route[i + 1]) for i in range(len(route) - 1))

    # ------------------------------------------------------------------ state
    def _event(self, o: Order, kind: str, text: str, **extra):
        e = dict(t=round(o.sim_t, 1), kind=kind, text=text, **extra)
        o.events.append(e)
        return e

    def snapshot(self, o: Order) -> dict:
        p = o.profile or {}
        ho = p.get("handover_time_s") or {}
        return dict(
            order_id=o.order_id, phase=o.phase, sim_t=round(o.sim_t, 1), rider=o.rider,
            eta_s=None if o.eta_s is None else round(o.eta_s),
            site=dict(site_id=o.site["site_id"], name=o.site["name"], kind=o.site["kind"],
                      polygon=o.site["polygon"], access_points=o.site["access_points"]),
            tower=o.tower, pin=o.pin, route=o.route, gate=o.gate, parking=o.parking,
            handover_point=o.handover_point, handover_type=o.handover_type,
            lead_s=o.lead_s, lead_explain=o.lead_explain, sync_enabled=o.sync_enabled,
            notified_at=o.notified_at, reply=o.reply, reply_at=o.reply_at,
            customer_at_hp_at=o.customer_at_hp_at, rider_at_hp_at=o.rider_at_hp_at,
            delivered_at=o.delivered_at, new_partner=o.new_partner,
            profile=dict(confidence=p.get("confidence"), trips=p.get("trips"),
                         gate_conf=(p.get("gate_day") or {}).get("confidence"),
                         gate_agreement=(p.get("gate_day") or {}).get("agreement"),
                         handover=(p.get("handover") or {}), handover_median_s=ho.get("median"),
                         handover_p80_s=ho.get("p80"), night_gate=bool(p.get("gate_night")),
                         parking=p.get("parking"), show_gate_hint=p.get("show_gate_hint"),
                         show_sync=p.get("show_sync")),
            events=o.events[-30:], fair=o.fair,
            manual=o.manual, pickup=o.pickup, route_pickup=o.route_pickup,
            accepted_at=o.accepted_at, reached_pickup_at=o.reached_pickup_at, picked_up_at=o.picked_up_at,
            arrived_at=o.arrived_at, called_at=o.called_at, calls=o.calls, helped=o.helped,
            drop_distance_m=round(self._route_len(o.route)),
            delivered_ago_s=None if o.delivered_wall is None else round(time.time() - o.delivered_wall),
        )

    async def broadcast(self, o: Order):
        msg = json.dumps(self.snapshot(o), default=float)
        dead = []
        for ws in list(o.subscribers):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            o.subscribers.discard(ws)

    # ------------------------------------------------------------------ inputs
    def reply(self, o: Order, choice: str):
        o.reply, o.reply_at = choice, o.sim_t
        text = {"coming": "Customer: Coming", "security": "Customer: Leave with security",
                "later2": "Customer: 2 more minutes"}[choice]
        self._event(o, "reply", text)
        if choice == "later2":
            o.cust_start_at = o.sim_t + 120.0
        elif choice == "coming":
            o.cust_start_at = o.sim_t

    def call(self, o: Order, auto: bool = False):
        """Rider calls the customer; the customer starts coming down once the call connects."""
        o.calls += 1
        if o.called_at is None:
            o.called_at = o.sim_t
        self._event(o, "call", "No reply to the nudge: rider calls the customer" if auto and o.sync_enabled
                    else "Rider calls the customer")
        if o.cust_start_at is None:
            o.cust_start_at = o.sim_t + sum(SIM.call_connect_s) / 2

    ACTIONS = {
        "accept": ("offered",),
        "reject": ("offered",),
        "reached_pickup": ("at_pickup",),
        "picked_up": ("pickup_wait",),
        "reached_drop": ("gate_check", "parking", "walk", "at_handover", "indoors"),
        "call": ("to_gate", "gate_check", "parking", "walk", "at_handover", "indoors"),
        "delivered": ("at_handover", "indoors"),
    }

    def action(self, o: Order, act: str) -> str | None:
        """Rider-app stage change. Returns an error string if not allowed now."""
        if act not in self.ACTIONS:
            return "unknown action"
        if o.phase not in self.ACTIONS[act]:
            return f"'{act}' not allowed in phase '{o.phase}'"
        if act == "accept":
            o.accepted_at = o.sim_t
            o.phase = "to_pickup"
            self._event(o, "accepted", f"Order accepted, heading to {o.pickup['name'] if o.pickup else 'pickup'}")
        elif act == "reject":
            o.phase = "rejected"
            o.delivered_at = o.sim_t
            self._event(o, "rejected", "Order rejected")
        elif act == "reached_pickup":
            o.reached_pickup_at = o.sim_t
            o.phase = "pickup_wait"
            self._event(o, "reached_pickup", f"Reached {o.pickup['name'] if o.pickup else 'pickup'}")
        elif act == "picked_up":
            o.picked_up_at = o.sim_t
            o.phase = "to_gate"
            self._event(o, "picked_up", f"Picked up, heading to {o.site['name']}")
        elif act == "reached_drop":
            if o.arrived_at is None:
                o.arrived_at = o.sim_t
                self._event(o, "arrived", "Rider marked 'Reached drop location'")
        elif act == "call":
            self.call(o)
        elif act == "delivered":
            self._deliver(o)
        return None

    def customer_at_handover(self, o: Order):
        if o.customer_at_hp_at is None:
            o.customer_at_hp_at = o.sim_t
            self._event(o, "customer_arrived", "Customer reached the handover point")

    # ------------------------------------------------------------------ loop
    async def run(self, o: Order, tick_s: float = 0.25):
        """Advance the simulated clock; o.speedup simulated seconds per real second."""
        route = o.route
        seg_len = [hav(route[i], route[i + 1]) for i in range(len(route) - 1)]
        total = sum(seg_len)
        post_hp = ((o.profile or {}).get("park_to_handover_point_s") or
                   hav(o.parking, o.handover_point) / WALK_MPS)
        drive_v = NOMINAL_SPEED_MPS * 0.95  # the replayed rider is a little slower than nominal
        dist = 0.0
        phase_t = 0.0
        pr = o.route_pickup
        p_len = [hav(pr[i], pr[i + 1]) for i in range(len(pr) - 1)]
        p_total = sum(p_len)
        p_dist = 0.0

        def along(rt, lens, d):
            acc = 0.0
            for i, L in enumerate(lens):
                if acc + L >= d:
                    f = (d - acc) / L if L else 1
                    a, b = rt[i], rt[i + 1]
                    return (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
                acc += L
            return rt[-1]

        o.phase = "offered" if o.manual else ("to_pickup" if pr else "to_gate")
        while o.delivered_at is None:
            await asyncio.sleep(tick_s)
            dt = tick_s * o.speedup
            o.sim_t += dt
            if o.phase in ("offered", "at_pickup", "pickup_wait"):
                pass  # waiting for the rider's tap
            elif o.phase == "to_pickup":
                p_dist = min(p_total, p_dist + drive_v * dt)
                o.rider = along(pr, p_len, p_dist)
                o.eta_s = None
                if p_dist >= p_total:
                    o.phase = "at_pickup" if o.manual else "to_gate"
                    self._event(o, "at_pickup", f"At {o.pickup['name'] if o.pickup else 'pickup'}")
            elif o.phase == "to_gate":
                dist = min(total, dist + drive_v * dt)
                o.rider = along(route, seg_len, dist)
                if o.boundary_at is None and hav(o.rider, (o.gate["lat"], o.gate["lon"])) < 60:
                    o.boundary_at = o.sim_t
                    self._event(o, "boundary", "Rider reached the site boundary")
                remaining = total - dist
                o.eta_s = remaining / NOMINAL_SPEED_MPS + GUARD_CHECK_S + PARK_S + post_hp
                if dist >= total:
                    o.phase, phase_t = "gate_check", 0.0
                    self._event(o, "gate", f"At {self._gate_label(o.gate)} ({o.gate.get('source')})")
            elif o.phase == "gate_check":
                phase_t += dt
                o.eta_s = max(0.0, GUARD_CHECK_S - phase_t) + PARK_S + post_hp
                if phase_t >= GUARD_CHECK_S:
                    o.phase, phase_t = "parking", 0.0
                    o.rider = o.parking
                    self._event(o, "parked", "Parked at the learned parking point" if (o.profile or {}).get("parking")
                                else "Parked at the gate")
            elif o.phase == "parking":
                phase_t += dt
                o.eta_s = max(0.0, PARK_S - phase_t) + post_hp
                if phase_t >= PARK_S:
                    o.phase, phase_t = "walk", 0.0
            elif o.phase == "walk":
                phase_t += dt
                f = min(1.0, phase_t / max(post_hp, 1))
                o.rider = (o.parking[0] + f * (o.handover_point[0] - o.parking[0]),
                           o.parking[1] + f * (o.handover_point[1] - o.parking[1]))
                o.eta_s = max(0.0, post_hp - phase_t)
                if f >= 1.0:
                    o.phase = "at_handover" if o.handover_type != "doorstep" else "indoors"
                    o.rider_at_hp_at = o.sim_t
                    phase_t = 0.0
                    self._event(o, "rider_at_hp", "Rider at the " + ("lobby" if o.handover_type == "lobby" else
                                                                      "gate" if o.handover_type == "gate" else "tower"))
                    if (not o.manual and not o.sync_enabled and o.handover_type != "doorstep"
                            and o.cust_start_at is None):
                        self.call(o)  # today: the rider calls on arrival
            elif o.phase == "indoors":
                phase_t += dt
                if not o.manual and phase_t >= 60 + (o.tower.get("levels") or 8) * FLOOR_H_M / LIFT_MPS:
                    self._deliver(o)
            elif o.phase == "at_handover":
                o.eta_s = 0.0
                if (not o.manual and o.sync_enabled and o.reply is None and o.cust_start_at is None
                        and o.rider_at_hp_at is not None and o.sim_t - o.rider_at_hp_at >= 30):
                    self.call(o, auto=True)  # no reply to the nudge: fall back to a call
                if not o.manual:
                    if o.reply == "security":
                        self._deliver(o, note="left with security")
                    elif o.customer_at_hp_at is not None:
                        phase_t += dt
                        if phase_t >= 10:
                            self._deliver(o)
            # trigger: once, when ETA to the handover point <= lead time
            if (o.sync_enabled and o.notified_at is None and o.lead_s is not None and o.eta_s is not None
                    and o.eta_s <= o.lead_s and o.phase in ("to_gate", "gate_check", "parking", "walk")):
                o.notified_at = o.sim_t
                gate_txt = self._gate_label(o.gate)
                where = f"to {gate_txt}" if o.handover_type == "gate" else "to your tower's lobby"
                self._event(o, "notify", f"Push to customer: Your rider reaches {gate_txt} in "
                            f"{max(1, round(o.eta_s / 60))} min. Your building has {o.handover_type} delivery, "
                            f"please come down {where} now.", lead_s=o.lead_s, eta_s=o.eta_s)
            # demo customer who tapped 'Coming' (or '2 more minutes') and did not press
            # "I'm here": reaches the handover point after their true come-down time
            if (o.cust_start_at is not None and o.customer_at_hp_at is None
                    and o.sim_t - o.cust_start_at >= o.cust_descent_s):
                self.customer_at_handover(o)
            await self.broadcast(o)
        await self.broadcast(o)

    def _deliver(self, o: Order, note: str | None = None):
        if note is None and o.reply == "security":
            note = "left with security"
        o.delivered_at = o.sim_t
        o.delivered_wall = time.time()
        o.phase = "delivered"
        wait = (o.delivered_at - o.rider_at_hp_at) if o.rider_at_hp_at is not None else 0.0
        ho = (o.delivered_at - o.boundary_at) if o.boundary_at is not None else None
        self._event(o, "delivered", "Delivered" + (f" ({note})" if note else ""), rider_wait_s=round(wait))
        o.fair = self.fair_lateness(o, ho, wait)
        try:
            with open(self.feedback_path, "a") as f:
                f.write(json.dumps(dict(order_id=o.order_id, site_id=o.site["site_id"], reply=o.reply,
                                        notified_at=o.notified_at, reply_at=o.reply_at,
                                        customer_at_hp_at=o.customer_at_hp_at, rider_at_hp_at=o.rider_at_hp_at,
                                        delivered_at=o.delivered_at, handover_s=ho, rider_wait_s=wait,
                                        sync=o.sync_enabled, calls=o.calls, manual=o.manual,
                                        ts=time.time())) + "\n")
        except OSError:
            pass

    def fair_lateness(self, o: Order, handover_s, wait_s) -> dict:
        """PDF 3.3: don't mark the rider late when the delay is the building's known
        handover time or the customer's late arrival; attach the evidence."""
        p = o.profile or {}
        p80 = (p.get("handover_time_s") or {}).get("p80")
        reasons, codes = [], []
        if p80 and handover_s is not None and handover_s <= p80 + 30:
            reasons.append(f"handover took {handover_s/60:.1f} min, within this building's usual p80 of {p80/60:.1f} min")
            codes.append(dict(code="within_p80", handover_s=round(handover_s), p80_s=round(p80)))
        if o.reply == "later2":
            reasons.append("customer asked for 2 more minutes")
            codes.append(dict(code="customer_later"))
        if o.customer_at_hp_at and o.rider_at_hp_at and o.customer_at_hp_at > o.rider_at_hp_at + 30:
            late = o.customer_at_hp_at - o.rider_at_hp_at
            reasons.append(f"customer reached the handover point {late/60:.1f} min after the rider")
            codes.append(dict(code="customer_late", late_s=round(late)))
        return dict(handover_s=None if handover_s is None else round(handover_s), rider_wait_s=round(wait_s),
                    building_p80_s=p80, excuse_lateness=bool(reasons), evidence=reasons, evidence_codes=codes)
