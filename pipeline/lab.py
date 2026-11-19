"""Learning-stages demo data ("how DropSync behaves after 0, 1, 5, 10, 11 ... trips").

For a few buildings the trip-level model never saw in training, simulate scenarios on the
real map and record, after every delivery, what DropSync would show the NEXT rider and why.

Scenarios
  first_visits      a building with no history; deliveries arrive one by one
  gate_closes       gate A works for 15 deliveries, then guards close it (riders sent to B)
  ignores_refused   10 normal deliveries; the 11th rider ignores the hint, goes to gate B, is
                    turned away there and comes back to A
  ignores_open      same, but gate B lets him in (both gates work)

Output: data/out/lab.json (served by GET /api/lab).  Usage: python -m pipeline.lab
"""
from __future__ import annotations

import json
import math
from dataclasses import replace

import numpy as np
import pandas as pd

from .config import OUT_DIR, SIM
from dataclasses import replace as dc_replace

from .profile_builder import HALF_LIFE_DAYS, build_profiles, build_site_profile
from .simulate import Simulator, load_noise, load_world

SITES = ["way/122737532", "way/41748192", "way/122738032"]   # held out from the entry model's training
TS_COLS = ["assigned_ts", "arrived_ts", "delivered_ts", "truth_boundary_ts", "truth_drive_end_ts", "truth_rider_at_hp_ts"]


def _shift(trips, pings, seconds, tag):
    trips = trips.copy()
    pings = pings.copy()
    for c in TS_COLS:
        trips[c] = trips[c] + seconds
    trips["day"] = trips["day"] + int(seconds // 86400)
    pings["ts"] = pings["ts"] + seconds
    trips["trip_id"] = trips["trip_id"] + tag
    pings["trip_id"] = pings["trip_id"] + tag
    return trips, pings


def _run(world, noise, site, patch, sim, n, seed):
    S = Simulator(world, replace(sim, seed=seed), noise)
    base = S.make_truth(site)
    S.make_truth = lambda s: {**base, **patch, "towers": base["towers"]}
    _, trips, pings = S.simulate_site(site.site_id, orders_override=n)
    return trips.sort_values("assigned_ts").reset_index(drop=True), pings


def scenario(world, noise, site, A, B, kind):
    quiet = replace(SIM, night_gate_change_prob=0, rule_change_prob=0, days=30)
    normal = dict(day_gate=A.ap_id, night_gate=A.ap_id, changed_gate=None, change_day=None, handover_type="lobby")
    if kind == "first_visits":
        return _run(world, noise, site, normal, quiet, 30, 11)
    if kind == "gate_closes":
        t1, p1 = _run(world, noise, site, normal, replace(quiet, days=30), 15, 12)
        closed = dict(normal, changed_gate=B.ap_id, change_day=0)
        t2, p2 = _run(world, noise, site, closed,
                      replace(quiet, days=14, wrong_gate_admitted_prob=0.0, stale_memory_days=14, stale_memory_prob=0.6), 20, 13)
        t2, p2 = _shift(t2, p2, 31 * 86400, "-b")
        return pd.concat([t1, t2], ignore_index=True), pd.concat([p1, p2], ignore_index=True)
    # 11th rider ignores the hint and heads for gate B
    t1, p1 = _run(world, noise, site, normal, replace(quiet, days=20), 20, 11)
    first10, rest = t1.iloc[:10], t1.iloc[10:]
    admitted = 1.0 if kind == "ignores_open" else 0.0
    tf, pf = _run(world, noise, site, dict(normal, force_choice=B.ap_id), replace(quiet, days=1, wrong_gate_admitted_prob=admitted), 1, 14)
    gap = float(first10.delivered_ts.max() + 600 - tf.assigned_ts.min())
    tf, pf = _shift(tf, pf, gap, "-x")
    rest_shift = float(tf.delivered_ts.max() + 600 - rest.assigned_ts.min())
    rest, prest = _shift(rest, p1[p1.trip_id.isin(rest.trip_id)], max(rest_shift, 0.0), "")
    trips = pd.concat([first10, tf, rest], ignore_index=True)
    pings = pd.concat([p1[p1.trip_id.isin(first10.trip_id)], pf, prest], ignore_index=True)
    return trips, pings


def _ap_road(world, site):
    return {a.ap_id: world.road_name_near(a.out_node) for a in site.aps}


def build():
    world = load_world()
    noise = load_noise()
    S0 = Simulator(world, SIM, noise)
    out = {"sites": [], "note": "Simulated deliveries on the real OSM map; buildings not used to train the trip-level model."}
    for sid in SITES:
        site = world.sites[sid]
        cand = S0.candidates(site)
        A = cand[0]
        B = max(cand[1:], key=lambda b: math.dist((b.x, b.y), (A.x, A.y)))
        roads = _ap_road(world, site)
        sd = dict(site_id=sid, name=site.name,
                  polygon=[[round(la, 6), round(lo, 6)] for lo, la in site.poly_ll.exterior.coords],
                  gates=[dict(ap_id=a.ap_id, lat=round(a.lat, 6), lon=round(a.lon, 6), osm_gate=a.osm_gate,
                              road=roads[a.ap_id], label="A" if a.ap_id == A.ap_id else ("B" if a.ap_id == B.ap_id else None))
                         for a in cand],
                  scenarios={})
        for kind in ["first_visits", "gate_closes", "ignores_refused", "ignores_open"]:
            trips, pings = scenario(world, noise, site, A, B, kind)
            # read every trip ONCE (the expensive part); each step then only recounts
            _, ev_all = build_profiles(world, trips, pings, return_evidence=True)
            ev_by = {e.trip_id: e for e in ev_all.get(sid, [])}
            steps = []
            for k in range(0, len(trips) + 1):
                prof = None
                if k:
                    t_ref = float(trips.delivered_ts.iloc[k - 1]) + 3600
                    evk = [dc_replace(ev_by[tid], weight=0.5 ** ((t_ref - ev_by[tid].ts) / 86400 / HALF_LIFE_DAYS))
                           for tid in trips.trip_id.iloc[:k] if tid in ev_by]
                    prof = build_site_profile(world, site, evk) if evk else None
                g = (prof or {}).get("gate_day") or {}
                h = (prof or {}).get("handover") or {}
                step = dict(k=k, rider=dict(
                    hint_shown=bool(prof and prof.get("show_gate_hint")),
                    gate=(g.get("ap_id") if g else None), probability=g.get("probability"),
                    confidence=g.get("confidence"), handover_type=h.get("type"), handover_conf=h.get("confidence"),
                    sync_shown=bool(prof and prof.get("show_sync")), lead_s=(prof or {}).get("come_down_lead_s"),
                    usual_handover_s=((prof or {}).get("handover_time_s") or {}).get("median")),
                    gates=[dict(ap_id=x["ap_id"], trips=x["trips"], refusals=x["refusals"], closed=x["closed"],
                                probability=x["probability"]) for x in (g.get("gates") or []) if x.get("ap_id")])
                if k:
                    t = trips.iloc[k - 1]
                    e = ev_by.get(t.trip_id)
                    pg = pings[pings.trip_id == t.trip_id].sort_values("ts")
                    pg = pg[pg.ts <= t.delivered_ts]
                    idx = np.linspace(0, len(pg) - 1, min(len(pg), 45)).astype(int) if len(pg) else []
                    near = lambda xy: min(cand, key=lambda a: math.dist((a.x, a.y), xy)).ap_id if xy else None
                    true_gate = Simulator.true_gate({**{"day_gate": A.ap_id, "night_gate": A.ap_id,
                                                        "changed_gate": B.ap_id if kind == "gate_closes" else None,
                                                        "change_day": 31 if kind == "gate_closes" else None}}, int(t.day), 13)
                    step["trip"] = dict(
                        path=[[round(float(pg.lat.iloc[i]), 6), round(float(pg.lon.iloc[i]), 6)] for i in idx],
                        read_entry=near(e.cross_xy) if e and e.cross_xy else None,
                        read_refused=[near(r[:2]) for r in (e.refusals if e else [])],
                        true_entry=t.truth_entry_ap, chooser=t.truth_chooser, wrong_gate=bool(t.truth_wrong_gate),
                        admitted=bool(t.truth_admitted), true_gate=true_gate,
                        minutes=round(float(t.delivered_ts - t.truth_boundary_ts) / 60, 1))
                steps.append(step)
            sd["scenarios"][kind] = steps
            print(f"[lab] {site.name} / {kind}: {len(trips)} deliveries")
        out["sites"].append(sd)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "lab.json").write_text(json.dumps(out, separators=(",", ":"), default=float))
    print(f"[lab] wrote {OUT_DIR / 'lab.json'} ({(OUT_DIR / 'lab.json').stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    build()
