"""Trip-level ML model: 'which gate did this rider get in through?' and 'was this rider
turned away at this gate?', trained on AUGMENTED simulated trips.

Why this is a legitimate use of simulated data
----------------------------------------------
The model learns to READ A NOISY GPS TRACE (the physics), not each building's rules:
  * the map is real (OSM gates, walls, roads), GPS noise is measured from real Indian
    traces, and the label for every trip is exact (the simulator knows which gate the
    rider used and where he was refused);
  * conditions are randomised (domain randomisation): GPS noise 0.7-2x the measured level,
    pings every 5-30 s, many first-time riders, guards who sometimes let wrong-gate riders
    in, gates that close mid-way, different handover rules;
  * it is tested on BUILDINGS IT NEVER SAW.
What it can NOT learn from simulation: which gate a given building uses, or how real
guards and customers behave. That is learned per building, online, from real trips
(profile_builder: Bayesian counts over these per-trip readings).

Usage:
  python -m pipeline.entry_model train      # simulate ~15k augmented trips, train, evaluate
"""
from __future__ import annotations

import json
import math
import time
import zlib
from dataclasses import replace

import numpy as np
import pandas as pd
import shapely

from .config import DATA, EVAL_DIR, SIM
from .stops import clean_pings, detect_stops

MODEL_PATH = DATA / "models" / "entry_model.joblib"
EDGE_M = 5.0
NEAR_M = 40.0
FEATURES = [
    "min_d", "min_d_outside", "n_inside_near", "max_depth_near", "n_near30", "stop_near_s",
    "first_near_rank", "last_near_to_deep_s", "visited_before_deep", "dist_to_first_deep",
    "frac_inside_after_visit", "dist_final_stop", "speed_after_visit", "frac_time_near",
    "osm_gate", "n_aps", "ping_interval_s", "median_acc", "has_deep", "near_is_last_before_deep",
]


def trip_arrays(world, site, g: pd.DataFrame, deliv_ts: float):
    g = g[g.ts <= deliv_ts + 5]
    xs, ys = map(np.asarray, world.proj.to_xy(g.lon.to_numpy(), g.lat.to_numpy()))
    ts = g.ts.to_numpy()
    acc = g["accuracy_m"].fillna(5.0).to_numpy() if "accuracy_m" in g else np.full(len(xs), 5.0)
    if not len(xs):
        return None
    pts = shapely.points(xs, ys)
    inside = shapely.contains(site.poly, pts)
    depth = np.where(inside, shapely.distance(site.poly.exterior, pts), 0.0)
    return xs, ys, ts, acc, depth


def ap_features(site, arr, stops_xy, final_xy):
    """One feature row per access point of the site for one trip."""
    xs, ys, ts, acc, depth = arr
    n = len(xs)
    deep = np.where(depth >= np.maximum(12.0, acc))[0]
    jj = int(deep[0]) if len(deep) else None
    dts = np.diff(ts)
    ping = float(np.median(dts)) if len(dts) else 15.0
    total_t = max(ts[-1] - ts[0], 1.0)
    first_near_t = {}
    rows = []
    for ap in site.aps:
        d = np.hypot(xs - ap.x, ys - ap.y)
        near40 = d <= NEAR_M
        if near40.any():
            first_near_t[ap.ap_id] = ts[np.argmax(near40)]
        rows.append((ap, d, near40))
    order = sorted(first_near_t, key=first_near_t.get)
    # which AP was visited last before the first deep fix
    last_before = None
    if jj is not None:
        best_t = -1
        for ap, d, near40 in rows:
            idx = np.where(near40[:jj + 1])[0]
            if len(idx) and ts[idx[-1]] > best_t:
                best_t, last_before = ts[idx[-1]], ap.ap_id
    out = []
    for ap, d, near40 in rows:
        shallow = depth < EDGE_M
        idx = np.where(near40)[0]
        last_visit = int(idx[-1]) if len(idx) else None
        after = slice(last_visit + 1, n) if last_visit is not None else slice(n, n)
        if last_visit is not None and last_visit + 1 < n:
            k = last_visit + 1
            sp = math.dist((xs[last_visit], ys[last_visit]), (xs[k], ys[k])) / max(ts[k] - ts[last_visit], 1.0)
        else:
            sp = 0.0
        stop_s = sum(dur for (sx, sy, st, dur) in stops_xy if math.dist((sx, sy), (ap.x, ap.y)) <= 35.0)
        if jj is not None:
            before = np.where(near40[:jj + 1])[0]
            lnd = float(ts[jj] - ts[before[-1]]) if len(before) else 9999.0
            dfd = math.dist((ap.x, ap.y), (xs[jj], ys[jj]))
        else:
            lnd, dfd = 9999.0, 9999.0
        out.append((ap, dict(
            min_d=float(d.min()),
            min_d_outside=float(d[shallow].min()) if shallow.any() else 9999.0,
            n_inside_near=int(((depth >= EDGE_M) & near40).sum()),
            max_depth_near=float(depth[near40].max()) if near40.any() else 0.0,
            n_near30=int((d <= 30).sum()),
            stop_near_s=float(stop_s),
            first_near_rank=float(order.index(ap.ap_id)) if ap.ap_id in order else 9.0,
            last_near_to_deep_s=lnd,
            visited_before_deep=float(lnd < 9999.0),
            dist_to_first_deep=dfd,
            frac_inside_after_visit=float((depth[after] >= EDGE_M).mean()) if last_visit is not None and last_visit + 1 < n else 0.0,
            dist_final_stop=math.dist((ap.x, ap.y), final_xy) if final_xy is not None else 9999.0,
            speed_after_visit=float(sp),
            frac_time_near=float(near40.sum() * ping / total_t),
            osm_gate=float(ap.osm_gate), n_aps=float(len(site.aps)), ping_interval_s=ping,
            median_acc=float(np.median(acc)), has_deep=float(jj is not None),
            near_is_last_before_deep=float(last_before == ap.ap_id),
        )))
    return out


def trip_rows(world, site, trip, g, stops):
    arr = trip_arrays(world, site, g, trip.delivered_ts)
    if arr is None:
        return []
    st = stops[stops.start_ts <= trip.delivered_ts + 5] if len(stops) else stops
    stops_xy = []
    final_xy = None
    for r in st.itertuples():
        sx, sy = world.proj.to_xy(r.lon, r.lat)
        stops_xy.append((sx, sy, r.start_ts, r.duration_s))
    if stops_xy:
        cand = [s for s in stops_xy if site.poly.buffer(60).contains(shapely.Point(s[0], s[1]))]
        if cand:
            final_xy = cand[-1][:2]
    return ap_features(site, arr, stops_xy, final_xy)


class EntryModel:
    def __init__(self, entry_clf, refusal_clf):
        self.entry_clf = entry_clf
        self.refusal_clf = refusal_clf

    def predict_trip(self, rows):
        """-> (entry access point or None, entry probability, [refused access points])"""
        if not rows:
            return None, 0.0, []
        X = np.array([[f[k] for k in FEATURES] for _, f in rows])
        pe = self.entry_clf.predict_proba(X)[:, 1]
        pr = self.refusal_clf.predict_proba(X)[:, 1]
        i = int(pe.argmax())
        entry = rows[i][0] if pe[i] >= 0.5 else None
        refused = [ap for (ap, _), p in zip(rows, pr) if p >= 0.5 and (entry is None or ap.ap_id != entry.ap_id)]
        return entry, float(pe[i]), refused


def load_model():
    if not MODEL_PATH.exists():
        return None
    import joblib
    d = joblib.load(MODEL_PATH)   # plain dict of the two classifiers (no pickled custom class)
    return EntryModel(d["entry"], d["refusal"])


# ------------------------------------------------------------------------- training
def _split_sites(world, sim_obj):
    sites = sorted(s.site_id for s in world.sites.values() if len(sim_obj.candidates(s)) >= 2)
    test = [s for s in sites if zlib.crc32(s.encode()) % 10 < 3]   # ~30 % of buildings held out
    train = [s for s in sites if s not in set(test)]
    return train, test


def _rows_for(world, trips, pings):
    """Feature rows + labels for every (trip, access point)."""
    clean = clean_pings(pings)
    stops = detect_stops(clean)
    by = dict(tuple(clean.groupby("trip_id")))
    sb = dict(tuple(stops.groupby("trip_id")))
    empty = stops.iloc[0:0]
    out = []
    for t in trips.itertuples(index=False):
        g = by.get(t.trip_id)
        if g is None or len(g) < 3:
            continue
        site = world.sites[t.site_id]
        refused_ap = t.truth_chosen if (t.truth_wrong_gate and not t.truth_admitted) else None
        for ap, f in trip_rows(world, site, t, g, sb.get(t.trip_id, empty)):
            out.append(dict(f, trip_id=t.trip_id, site_id=t.site_id, ap_id=ap.ap_id,
                            y_entry=int(ap.ap_id == t.truth_entry_ap), y_refused=int(ap.ap_id == refused_ap)))
    return pd.DataFrame(out)


def generate(world, noise, site_ids, n_configs=6, orders_per_site=40, workers=12, seed=101):
    """Domain-randomised simulated trips (the augmentation)."""
    from .simulate import Simulator
    rng = np.random.default_rng(seed)
    frames_t, frames_p = [], []
    for c in range(n_configs):
        sim = replace(SIM, seed=seed + c,
                      ping_interval_s=float(rng.choice([5, 10, 15, 20, 30])),
                      new_to_site_share=float(rng.uniform(0.3, 0.7)),
                      wrong_gate_admitted_prob=float(rng.uniform(0.0, 0.6)),
                      rule_change_prob=float(rng.uniform(0.2, 0.6)),
                      night_gate_change_prob=float(rng.uniform(0.0, 0.5)),
                      stale_memory_prob=float(rng.uniform(0.3, 0.8)))
        nz = json.loads(json.dumps(noise))
        nz["stationary"]["sigma_per_axis_m"] *= float(rng.uniform(0.7, 2.0))
        S = Simulator(world, sim, nz)
        _, trips, pings = S.simulate(site_ids=site_ids, orders_override=orders_per_site, workers=workers)
        trips = trips.assign(trip_id=trips.trip_id + f"-c{c}")
        pings = pings.assign(trip_id=pings.trip_id + f"-c{c}")
        frames_t.append(trips)
        frames_p.append(pings)
        print(f"  config {c}: ping {sim.ping_interval_s:.0f}s noise x{nz['stationary']['sigma_per_axis_m'] / noise['stationary']['sigma_per_axis_m']:.2f} "
              f"new riders {sim.new_to_site_share:.0%} admitted {sim.wrong_gate_admitted_prob:.0%} -> {len(trips)} trips")
    return pd.concat(frames_t, ignore_index=True), pd.concat(frames_p, ignore_index=True)


def rule_predictions(world, trips, pings):
    """The hand-written rules' per-trip readings, for comparison."""
    from .profile_builder import build_profiles
    _, ev = build_profiles(world, trips, pings, return_evidence=True, entry_model=None)
    out = {}
    for sid, evs in ev.items():
        site = world.sites[sid]
        for e in evs:
            ent = None
            if e.cross_xy is not None and site.aps:
                ap = min(site.aps, key=lambda a: math.dist((a.x, a.y), e.cross_xy))
                ent = ap.ap_id if math.dist((ap.x, ap.y), e.cross_xy) <= 35 else None
            refs = set()
            for (rx, ry, _) in e.refusals:
                ap = min(site.aps, key=lambda a: math.dist((a.x, a.y), (rx, ry)))
                refs.add(ap.ap_id)
            out[e.trip_id] = (ent, refs)
    return out


def score(trips, pred):
    """pred: trip_id -> (entry ap or None, set of refused aps)"""
    t = trips.set_index("trip_id")
    ok = tot = 0
    rtp = rfp = rfn = 0
    det_ok = det_tot = 0
    for tid, (ent, refs) in pred.items():
        if tid not in t.index:
            continue
        r = t.loc[tid]
        tot += 1
        ok += ent == r.truth_entry_ap
        true_ref = {r.truth_chosen} if (r.truth_wrong_gate and not r.truth_admitted) else set()
        rtp += len(refs & true_ref)
        rfp += len(refs - true_ref)
        rfn += len(true_ref - refs)
        if true_ref:
            det_tot += 1
            det_ok += ent == r.truth_entry_ap
    return dict(trips=tot, entry_accuracy=round(ok / max(tot, 1), 4),
                detour_trips=det_tot, detour_entry_accuracy=round(det_ok / max(det_tot, 1), 4),
                refusal_precision=round(rtp / max(rtp + rfp, 1), 4), refusal_recall=round(rtp / max(rtp + rfn, 1), 4))


def main():
    import os
    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier
    from .simulate import Simulator, load_noise, load_world
    t0 = time.time()
    world = load_world()
    noise = load_noise()
    S0 = Simulator(world, SIM, noise)
    train_sites, test_sites = _split_sites(world, S0)
    workers = int(os.environ.get("DROPSYNC_WORKERS", "12"))
    print(f"[entry-model] {len(train_sites)} training buildings, {len(test_sites)} held-out buildings")
    print("[entry-model] simulating augmented training trips")
    tr_trips, tr_pings = generate(world, noise, train_sites, n_configs=6, orders_per_site=40, workers=workers)
    rows = _rows_for(world, tr_trips, tr_pings)
    X, ye, yr = rows[FEATURES].to_numpy(), rows.y_entry.to_numpy(), rows.y_refused.to_numpy()
    print(f"[entry-model] {tr_trips.trip_id.nunique()} trips -> {len(rows)} (trip, gate) rows; "
          f"{ye.sum()} entries, {yr.sum()} refusals")
    entry_clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=0).fit(X, ye)
    refusal_clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=0,
                                                 class_weight="balanced").fit(X, yr)
    model = EntryModel(entry_clf, refusal_clf)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"entry": entry_clf, "refusal": refusal_clf, "features": FEATURES}, MODEL_PATH)

    # ---- evaluation on buildings the model never saw, under several conditions
    print("[entry-model] evaluating on held-out buildings")
    results = []
    tests = [("normal (measured noise, 15 s pings)", replace(SIM, seed=900), 1.0),
             ("many first-time riders + gate closures", replace(SIM, seed=901, new_to_site_share=0.5,
                                                                rule_change_prob=0.6, wrong_gate_admitted_prob=0.0), 1.0),
             ("2x GPS noise", replace(SIM, seed=902, new_to_site_share=0.4), 2.0),
             ("sparse pings (30 s)", replace(SIM, seed=903, ping_interval_s=30.0, new_to_site_share=0.4), 1.0)]
    for name, sim, scale in tests:
        nz = json.loads(json.dumps(noise))
        nz["stationary"]["sigma_per_axis_m"] *= scale
        _, te_trips, te_pings = Simulator(world, sim, nz).simulate(site_ids=test_sites, orders_override=40, workers=workers)
        rule = score(te_trips, rule_predictions(world, te_trips, te_pings))
        te_rows = _rows_for(world, te_trips, te_pings)
        pred = {}
        for tid, grp in te_rows.groupby("trip_id"):
            site = world.sites[grp.site_id.iloc[0]]
            rws = [(next(a for a in site.aps if a.ap_id == r.ap_id), {k: getattr(r, k) for k in FEATURES})
                   for r in grp.itertuples()]
            ent, _, refs = model.predict_trip(rws)
            pred[tid] = (ent.ap_id if ent else None, {a.ap_id for a in refs})
        ml = score(te_trips, pred)
        results.append(dict(condition=name, rules=rule, ml=ml))
        print(f"  {name}: rules entry {rule['entry_accuracy']:.1%} (detours {rule['detour_entry_accuracy']:.1%}, "
              f"refusal P/R {rule['refusal_precision']:.0%}/{rule['refusal_recall']:.0%}) | "
              f"ML entry {ml['entry_accuracy']:.1%} (detours {ml['detour_entry_accuracy']:.1%}, "
              f"refusal P/R {ml['refusal_precision']:.0%}/{ml['refusal_recall']:.0%})")
    imp = dict(zip(FEATURES, [0.0] * len(FEATURES)))
    out = dict(
        what="Trip-level gate reading (entry gate / refused gate) learned from augmented simulated trips",
        training=dict(trips=int(tr_trips.trip_id.nunique()), rows=int(len(rows)), buildings=len(train_sites),
                      configs="6 randomised configs: GPS noise 0.7-2x measured, pings 5-30 s, 30-70% first-time riders, "
                              "0-60% wrong-gate riders let in, 20-60% buildings with a gate change"),
        held_out_buildings=len(test_sites), results=results, features=list(imp),
        seconds=round(time.time() - t0))
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "entry_model.json").write_text(json.dumps(out, indent=2, default=float))
    print(f"[entry-model] done in {time.time() - t0:.0f}s -> {MODEL_PATH}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        main()
    else:
        print(__doc__)
