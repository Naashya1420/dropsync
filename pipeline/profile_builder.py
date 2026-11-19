"""Profile builder (PDF 4.1 'nightly batch, per building').

Inputs it is allowed to see (what Eternal's delivery system already has):
  pings:  trip_id, ts, lat, lon, accuracy_m
  trips:  trip_id, site_id, assigned_ts, arrived_ts, delivered_ts, pin_lat, pin_lon
  OSM:    site polygons, access points, gates, buildings, parking
It never reads columns starting with 'truth_'.

Steps (PDF 4.1):
  1. stop detection            -> stops.detect_stops on cleaned pings
  2. DBSCAN stop clustering    -> parking point
  3. gate & entry inference    -> boundary crossing of each trip, DBSCAN, snap to OSM access point
  4. handover-type inference   -> GPS gap before 'delivered' + where the final stop is
  5. time-of-day split         -> separate night (23:00-06:00) gate when evidence differs
  6. confidence gate           -> trips, agreement, 'is it faster' check
Recency weighting (PDF 4.6 'old evidence decays'): weight = 0.5 ** (age_days / HALF_LIFE_DAYS).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, Point
from sklearn.cluster import DBSCAN

from .simulate import IST
from .sitemodel import Site, World
from .stops import clean_pings, detect_stops

HALF_LIFE_DAYS = 30.0
GATE_EPS_M = 20.0
GATE_SNAP_M = 35.0
PARK_EPS_M = 15.0
DOORSTEP_GAP_S = 45.0     # no usable fix for this long before 'delivered' => rider was indoors
GATE_BOUNDARY_M = 30.0    # final stop within this distance OUTSIDE the boundary => gate handover
EDGE_M = 5.0              # final stop more than this INSIDE the boundary => lobby handover
SUSTAIN_FIXES = 3         # an entry counts once the rider stays inside for this many fixes
NIGHT_MIN_TRIPS = 6
CHANGE_WINDOW_DAYS = 14
CHANGE_MIN_TRIPS = 5
CHANGE_MIN_AGREE = 0.70
CONF_HIGH = (40, 0.75)    # (trips, agreement)
CONF_MED = (12, 0.60)


def _wmedian(v, w):
    v = np.asarray(v, float)
    w = np.asarray(w, float)
    if len(v) == 0:
        return None
    o = np.argsort(v)
    cw = np.cumsum(w[o])
    return float(v[o][np.searchsorted(cw, 0.5 * cw[-1])])


def _wquant(v, w, q):
    v = np.asarray(v, float)
    w = np.asarray(w, float)
    if len(v) == 0:
        return None
    o = np.argsort(v)
    cw = np.cumsum(w[o])
    return float(v[o][min(len(v) - 1, np.searchsorted(cw, q * cw[-1]))])


@dataclass
class TripEvidence:
    trip_id: str
    site_id: str
    ts: float
    night: bool
    weight: float
    cross_xy: tuple | None
    cross_kind: str | None          # 'crossing' | 'outside_stop'
    park_xy: tuple | None
    final_xy: tuple | None
    htype: str | None
    handover_s: float | None        # boundary (GPS) -> delivered
    wait_at_hp_s: float | None      # final stop start -> delivered (lobby/gate)
    park_to_hp_s: float | None      # parking stop start -> final stop start
    pin_xy: tuple


def trip_evidence(world: World, site: Site, trip, g: pd.DataFrame, stops: pd.DataFrame, t_ref: float) -> TripEvidence:
    poly = site.poly
    deliv = trip.delivered_ts
    g = g[g.ts <= deliv + 5]
    xs, ys = world.proj.to_xy(g.lon.to_numpy(), g.lat.to_numpy())
    xs = np.asarray(xs)
    ys = np.asarray(ys)
    ts = g.ts.to_numpy()
    inside_raw = shapely.contains_xy(poly, xs, ys)
    # 3-fix majority filter: removes single-fix in/out flips caused by GPS jitter at the boundary
    inside = inside_raw.copy()
    if len(inside_raw) >= 3:
        inside[1:-1] = (inside_raw[:-2].astype(int) + inside_raw[1:-1] + inside_raw[2:]) >= 2
    near = shapely.contains_xy(poly.buffer(30), xs, ys)
    boundary_ts = float(ts[np.argmax(near)]) if near.any() else None

    # --- gate evidence: FIRST SUSTAINED outside -> inside transition before delivered.
    # (Later flips are GPS jitter near the boundary, e.g. a lobby next to the wall.)
    cross_xy, cross_kind = None, None
    trans = np.where((~inside[:-1]) & (inside[1:]))[0]
    for i in trans:
        after = inside[i + 1:i + 1 + SUSTAIN_FIXES]  # fewer if the trace ends: still accepted
        if after.all():
            seg = LineString([(xs[i], ys[i]), (xs[i + 1], ys[i + 1])])
            ip = seg.intersection(poly.exterior)
            if not ip.is_empty:
                p = ip if ip.geom_type == "Point" else min(ip.geoms, key=lambda q: q.distance(Point(xs[i], ys[i])))
                cross_xy, cross_kind = (p.x, p.y), "crossing"
                break

    # --- stops of this trip near the site
    st = stops[(stops.start_ts <= deliv + 5)]
    if len(st):
        sx, sy = world.proj.to_xy(st.lon.to_numpy(), st.lat.to_numpy())
        st = st.assign(x=np.asarray(sx), y=np.asarray(sy))
        st = st[shapely.contains_xy(poly.buffer(60), st.x.to_numpy(), st.y.to_numpy())]
    park_xy = final_xy = None
    park_start = final_start = None
    if len(st):
        f = st.iloc[-1]
        p0 = st.iloc[0]
        park_xy, park_start = (p0.x, p0.y), p0.start_ts
        final_xy, final_start = (f.x, f.y), f.start_ts
        if cross_xy is None and not poly.contains(Point(final_xy)) and poly.exterior.distance(Point(final_xy)) <= GATE_BOUNDARY_M:
            p = poly.exterior.interpolate(poly.exterior.project(Point(final_xy)))
            cross_xy, cross_kind = (p.x, p.y), "outside_stop"

    # --- handover type
    last_fix = ts[-1] if len(ts) else None
    gap = deliv - last_fix if last_fix is not None else None
    htype = None
    if gap is not None and gap >= DOORSTEP_GAP_S and world.dist_to_building(xs[-1], ys[-1], 40) <= 30:
        htype = "doorstep"
    elif final_xy is not None and final_start is not None and deliv - final_start >= 30:
        # Waiting outside the site (or on its edge) = gate handover; waiting inside = lobby.
        fp = Point(final_xy)
        inside_by = poly.exterior.distance(fp) if poly.contains(fp) else -poly.exterior.distance(fp)
        if inside_by > EDGE_M:
            htype = "lobby"
        elif inside_by >= -GATE_BOUNDARY_M:
            htype = "gate"
    wait = (deliv - final_start) if (htype in ("lobby", "gate") and final_start is not None) else None
    p2h = (final_start - park_start) if (final_start is not None and park_start is not None) else None
    hour = pd.Timestamp(trip.assigned_ts, unit="s", tz="UTC").tz_convert(IST).hour
    age_days = (t_ref - trip.assigned_ts) / 86400
    pin_xy = world.proj.to_xy(trip.pin_lon, trip.pin_lat)
    return TripEvidence(trip.trip_id, site.site_id, trip.assigned_ts, hour >= 23 or hour < 6,
                        0.5 ** (age_days / HALF_LIFE_DAYS), cross_xy, cross_kind, park_xy, final_xy, htype,
                        (deliv - boundary_ts) if boundary_ts else None, wait, p2h, pin_xy)


def _confidence(n: int, agree: float) -> str:
    if n >= CONF_HIGH[0] and agree >= CONF_HIGH[1]:
        return "high"
    if n >= CONF_MED[0] and agree >= CONF_MED[1]:
        return "medium"
    return "low"


def _gate_vote(world: World, site: Site, ev: list[TripEvidence], use_recency: bool):
    """Each trip's entry point votes for the nearest OSM access point (within
    GATE_SNAP_M). Entries far from every mapped access point are clustered with
    DBSCAN into 'learned' gates that OSM does not have. The winner is the gate
    that collects the most (recency-weighted) votes from FAST trips (handover
    time <= site median), as in PDF 3.1 'where fast trips cross the boundary'."""
    pts = [e for e in ev if e.cross_xy is not None]
    if len(pts) < 2:
        return None
    X = np.array([e.cross_xy for e in pts])
    w = np.array([e.weight if use_recency else 1.0 for e in pts])
    ht = np.array([e.handover_s if e.handover_s is not None else np.nan for e in pts])
    med = np.nanmedian(ht) if np.isfinite(ht).any() else np.inf
    fast = np.where(np.isfinite(ht), ht <= med, True)
    keys = np.empty(len(pts), dtype=object)
    ap_xy = np.array([(a.x, a.y) for a in site.aps]) if site.aps else np.zeros((0, 2))
    if len(ap_xy):
        d = np.hypot(X[:, None, 0] - ap_xy[None, :, 0], X[:, None, 1] - ap_xy[None, :, 1])
        j = d.argmin(1)
        near = d[np.arange(len(pts)), j] <= GATE_SNAP_M
        for i in np.where(near)[0]:
            keys[i] = site.aps[j[i]].ap_id
    else:
        near = np.zeros(len(pts), bool)
    far = np.where(~near)[0]
    if len(far) >= 2:
        lab = DBSCAN(eps=GATE_EPS_M, min_samples=2).fit(X[far]).labels_
        for i, l in zip(far, lab):
            keys[i] = f"learned{l}" if l >= 0 else None
    clusters = []
    for k in {k for k in keys if k is not None}:
        m = keys == k
        ap = next((a for a in site.aps if a.ap_id == k), None)
        cx, cy = (ap.x, ap.y) if ap else (np.average(X[m, 0], weights=w[m]), np.average(X[m, 1], weights=w[m]))
        clusters.append(dict(
            key=k, x=cx, y=cy, ap=ap, n=int(m.sum()),
            score_fast=float(w[m & fast].sum()), score_all=float(w[m].sum()),
            median_handover_s=float(np.nanmedian(ht[m])) if np.isfinite(ht[m]).any() else None))
    if not clusters:
        return None
    cl = sorted(clusters, key=lambda c: (-c["score_fast"], -c["score_all"]))
    total_fast = sum(c["score_fast"] for c in cl) or 1.0
    win = cl[0]
    others_ht = [c["median_handover_s"] for c in cl[1:] if c["median_handover_s"] is not None and c["n"] >= 2]
    faster = (not others_ht) or (win["median_handover_s"] is not None and win["median_handover_s"] <= min(others_ht))
    return dict(win=win, agreement=win["score_fast"] / total_fast, n=len(pts), faster=bool(faster), clusters=cl)


def build_site_profile(world: World, site: Site, ev: list[TripEvidence], use_recency: bool = True) -> dict:
    n = len(ev)
    w = np.array([e.weight if use_recency else 1.0 for e in ev])
    prof = dict(site_id=site.site_id, name=site.name, kind=site.kind, trips=n,
                effective_trips=round(float(w.sum()), 1))

    def gate_block(subset):
        v = _gate_vote(world, site, subset, use_recency)
        if v is None:
            return None
        win = v["win"]
        lat, lon = world.ll(win["x"], win["y"])
        ap = win["ap"]
        return dict(
            ap_id=ap.ap_id if ap else None, lat=round(lat, 6), lon=round(lon, 6),
            osm_gate=bool(ap and ap.osm_gate), gate_osm_id=ap.gate_osm_id if ap else None,
            gate_name=(ap.gate_name if ap and ap.gate_name else None),
            in_osm=bool(ap and ap.osm_gate), trips=v["n"], agreement=round(v["agreement"], 3),
            faster_than_alternatives=v["faster"], confidence=_confidence(v["n"], v["agreement"]),
            median_handover_s=win["median_handover_s"],
            alternatives=[dict(ap_id=c["ap"].ap_id if c["ap"] else None, trips=c["n"],
                               lat=round(world.ll(c["x"], c["y"])[0], 6), lon=round(world.ll(c["x"], c["y"])[1], 6),
                               median_handover_s=c["median_handover_s"]) for c in v["clusters"][1:4]],
        )

    day_ev = [e for e in ev if not e.night]
    night_ev = [e for e in ev if e.night]
    prof["gate_day"] = gate_block(day_ev)
    # Change detection (PDF 4.6 'when a gate closes ... recent trips shift the profile'):
    # if the last CHANGE_WINDOW_DAYS of day trips agree on a different gate, switch to it.
    prof["gate_changed_recently"] = False
    if prof["gate_day"] and day_ev:
        t_last = max(e.ts for e in day_ev)
        recent = [e for e in day_ev if e.ts >= t_last - CHANGE_WINDOW_DAYS * 86400]
        rv = _gate_vote(world, site, recent, use_recency=False) if len(recent) >= CHANGE_MIN_TRIPS else None
        if (rv and rv["n"] >= CHANGE_MIN_TRIPS and rv["agreement"] >= CHANGE_MIN_AGREE
                and rv["win"]["key"] != (prof["gate_day"]["ap_id"] or "")):
            g = gate_block(recent)
            if g:
                g["confidence"] = "medium" if g["confidence"] == "low" else g["confidence"]
                prof["gate_day"] = g
                prof["gate_changed_recently"] = True
    prof["gate_night"] = None
    if len(night_ev) >= NIGHT_MIN_TRIPS:
        gn = gate_block(night_ev)
        if gn and prof["gate_day"] and gn["ap_id"] != prof["gate_day"]["ap_id"] and gn["agreement"] >= CONF_MED[1]:
            prof["gate_night"] = gn

    # parking point
    pk = [e for e in ev if e.park_xy is not None]
    prof["parking"] = None
    if len(pk) >= 3:
        X = np.array([e.park_xy for e in pk])
        pw = np.array([e.weight if use_recency else 1.0 for e in pk])
        lab = DBSCAN(eps=PARK_EPS_M, min_samples=3).fit(X).labels_
        best = None
        for c in set(lab) - {-1}:
            m = lab == c
            sc = pw[m].sum()
            if best is None or sc > best[0]:
                best = (sc, np.average(X[m, 0], weights=pw[m]), np.average(X[m, 1], weights=pw[m]), int(m.sum()))
        if best:
            px, py = best[1], best[2]
            osm_p = min(site.osm_parking, key=lambda p: math.dist(p, (px, py)), default=None)
            snapped = osm_p is not None and math.dist(osm_p, (px, py)) <= 25
            lat, lon = world.ll(*(osm_p if snapped else (px, py)))
            prof["parking"] = dict(lat=round(lat, 6), lon=round(lon, 6), trips=best[3],
                                   share=round(best[0] / pw.sum(), 3), snapped_to_osm_parking=bool(snapped),
                                   inside_site=bool(site.poly.contains(Point(px, py))))

    # handover type
    typed = [(e.htype, e.weight if use_recency else 1.0) for e in ev if e.htype]
    prof["handover"] = None
    if typed:
        tot = sum(wt for _, wt in typed)
        votes = {}
        for t, wt in typed:
            votes[t] = votes.get(t, 0) + wt
        t_best = max(votes, key=votes.get)
        agree = votes[t_best] / tot
        prof["handover"] = dict(type=t_best, agreement=round(agree, 3), trips=len(typed),
                                confidence=_confidence(len(typed), agree),
                                votes={k: round(v / tot, 3) for k, v in votes.items()})

    # timing
    ho = [(e.handover_s, e.weight if use_recency else 1.0) for e in ev if e.handover_s is not None]
    if ho:
        v, wt = zip(*ho)
        prof["handover_time_s"] = dict(median=round(_wmedian(v, wt), 1), p80=round(_wquant(v, wt, 0.8), 1), trips=len(v))
    else:
        prof["handover_time_s"] = None
    wa = [(e.wait_at_hp_s, e.weight if use_recency else 1.0) for e in ev if e.wait_at_hp_s is not None]
    p2 = [(e.park_to_hp_s, e.weight if use_recency else 1.0) for e in ev if e.park_to_hp_s is not None]
    # Come-down lead time: how long before the rider reaches the handover point the
    # customer must start. Learned from the historical wait at the handover point
    # (includes the call the rider used to make, so it errs on the early side).
    # Once the sync is live, the backend refines it from 'Coming' tap -> delivered.
    prof["come_down_lead_s"] = round(_wmedian(*zip(*wa)), 1) if len(wa) >= 5 else None
    prof["park_to_handover_point_s"] = round(_wmedian(*zip(*p2)), 1) if len(p2) >= 5 else None

    # tower floors from OSM (cold-start prior and per-tower adjustment)
    lv = [t.levels for t in site.towers if t.levels]
    prof["osm_levels"] = dict(towers=len(site.towers), towers_with_levels=len(lv),
                              median=float(np.median(lv)) if lv else None)

    # what the apps are allowed to show
    g = prof["gate_day"]
    h = prof["handover"]
    prof["show_gate_hint"] = bool(g and g["confidence"] in ("high", "medium") and g["faster_than_alternatives"])
    prof["show_sync"] = bool(h and h["type"] in ("lobby", "gate") and h["confidence"] in ("high", "medium")
                             and prof["come_down_lead_s"] is not None)
    prof["show_checkout_banner"] = bool(h and h["confidence"] in ("high", "medium"))
    levels_c = [g["confidence"] if g else "low", h["confidence"] if h else "low"]
    prof["confidence"] = "high" if all(c == "high" for c in levels_c) else (
        "medium" if all(c in ("high", "medium") for c in levels_c) else "low")
    return prof


def build_profiles(world: World, trips: pd.DataFrame, pings: pd.DataFrame, use_recency: bool = True,
                   t_ref: float | None = None, return_evidence: bool = False):
    trips = trips[[c for c in trips.columns if not c.startswith("truth_")]]
    t_ref = t_ref or float(trips.delivered_ts.max()) + 3600
    clean = clean_pings(pings[pings.trip_id.isin(trips.trip_id)])
    stops = detect_stops(clean)
    by_trip = dict(tuple(clean.groupby("trip_id")))
    stops_by = dict(tuple(stops.groupby("trip_id")))
    empty_stops = stops.iloc[0:0]
    evidence: dict[str, list[TripEvidence]] = {}
    for tr in trips.itertuples(index=False):
        site = world.sites.get(tr.site_id)
        g = by_trip.get(tr.trip_id)
        if site is None or g is None or len(g) < 3:
            continue
        evidence.setdefault(tr.site_id, []).append(
            trip_evidence(world, site, tr, g, stops_by.get(tr.trip_id, empty_stops), t_ref))
    profiles = {sid: build_site_profile(world, world.sites[sid], ev, use_recency) for sid, ev in evidence.items()}
    if return_evidence:
        return profiles, evidence
    return profiles
