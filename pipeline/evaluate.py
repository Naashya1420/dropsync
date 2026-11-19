"""Evaluation of DropSync on the simulated Indian delivery history.

Honesty rules:
  * Profiles are learned on days 0-59 and evaluated on days 60-89 (out of sample).
  * Ground truth ('truth_*') is used ONLY here, never by the builder.
  * Every number in data/eval/metrics.json is tagged source="simulated" and comes
    with the assumption set used (config.SimAssumptions). GPS noise is measured
    from real OSM traces; map is real OSM.

Outputs data/eval/metrics.json with sections:
  profile_accuracy   gate / night gate / handover type / parking / handover time vs truth
  baselines          gate a new rider picks with navigation only
  recency            rule-change sites: with vs without recency weighting
  learning_curve     accuracy vs trips per site
  robustness         accuracy vs GPS noise x1..x3 and ping interval 5..20 s
  ab_sync            handover time, rider wait, customer wait, call rate: today vs DropSync
  pin_fixer          precision / recall of wrong-pin detection
  sizing             PDF 2.2 formula re-run with the simulated minutes saved
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import replace

import numpy as np
import pandas as pd

from .config import EVAL_DIR, SIM, SIM_DIR, sim_assumptions_dict
from .profile_builder import build_profiles, build_site_profile
from .simulate import BASE, Simulator, is_night, load_noise, load_world

TRAIN_DAYS = 60


def _site_truth_at(truth: dict, day: int, night: bool) -> str:
    return Simulator.true_gate(truth, day, 2 if night else 13)


def _acc(xs):
    xs = [x for x in xs if x is not None]
    return round(float(np.mean(xs)), 4) if xs else None


def profile_accuracy(world, profiles, truths, trips, eval_day: int):
    rows = []
    for sid, p in profiles.items():
        t = truths[sid]
        g = p.get("gate_day")
        tr = trips[trips.site_id == sid]
        true_day = _site_truth_at(t, eval_day, False)
        true_night = _site_truth_at(t, eval_day, True)
        # parking truth: where riders actually parked in the training window (most common spot)
        pk = tr[["truth_park_lat", "truth_park_lon"]].round(5).value_counts()
        park_err = None
        if p.get("parking") and len(pk):
            (plat, plon) = pk.index[0]
            park_err = float(np.hypot((p["parking"]["lat"] - plat) * 111_320,
                                      (p["parking"]["lon"] - plon) * 111_320 * math.cos(math.radians(plat))))
        ho_true = (tr.delivered_ts - tr.truth_boundary_ts).median() if len(tr) else None
        rows.append(dict(
            site_id=sid, trips=p["trips"], n_gates=t["n_candidate_gates"],
            gate_pred=g["ap_id"] if g else None, gate_true=true_day,
            gate_ok=(g["ap_id"] == true_day) if g else None,
            gate_shown=p["show_gate_hint"], gate_conf=g["confidence"] if g else None,
            night_differs=true_night != true_day,
            night_found=(p.get("gate_night") or {}).get("ap_id") == true_night if true_night != true_day else None,
            night_false_alarm=(p.get("gate_night") is not None) if true_night == true_day else None,
            type_pred=(p.get("handover") or {}).get("type"), type_true=t["handover_type"],
            type_ok=((p.get("handover") or {}).get("type") == t["handover_type"]) if p.get("handover") else None,
            type_conf=(p.get("handover") or {}).get("confidence"),
            sync_shown=p["show_sync"], banner_shown=p["show_checkout_banner"],
            park_err_m=park_err,
            ho_pred=(p.get("handover_time_s") or {}).get("median"), ho_true=float(ho_true) if ho_true is not None else None,
            rule_change=t["changed_gate"] is not None,
            night_trips=int(((tr.hour >= 23) | (tr.hour < 6)).sum()),
        ))
    df = pd.DataFrame(rows)
    multi = df[df.n_gates >= 2]
    shown = df[df.gate_shown]
    ho = df.dropna(subset=["ho_pred", "ho_true"])
    out = dict(
        sites=int(len(df)), sites_multi_gate=int(len(multi)),
        gate_accuracy_all=_acc(df.gate_ok), gate_accuracy_multi_gate=_acc(multi.gate_ok),
        gate_hint_coverage=round(float(df.gate_shown.mean()), 4),
        gate_hint_precision=_acc(shown.gate_ok),
        gate_hint_precision_multi_gate=_acc(shown[shown.n_gates >= 2].gate_ok),
        night_gate_sites=int(df.night_differs.sum()),
        night_gate_recall=_acc(df[df.night_differs].night_found),
        night_gate_sites_with_enough_trips=int((df.night_differs & (df.night_trips >= 6)).sum()),
        night_gate_recall_enough_trips=_acc(df[df.night_differs & (df.night_trips >= 6)].night_found),
        night_gate_false_alarm_rate=_acc(df[~df.night_differs].night_false_alarm),
        handover_type_accuracy=_acc(df.type_ok),
        handover_type_accuracy_shown=_acc(df[df.banner_shown].type_ok),
        checkout_banner_coverage=round(float(df.banner_shown.mean()), 4),
        sync_coverage_of_lobby_gate_sites=round(float(df[df.type_true.isin(["lobby", "gate"])].sync_shown.mean()), 4)
        if (df.type_true.isin(["lobby", "gate"])).any() else None,
        parking_error_m=dict(median=float(df.park_err_m.median()) if df.park_err_m.notna().any() else None,
                             p80=float(df.park_err_m.quantile(.8)) if df.park_err_m.notna().any() else None),
        handover_time_abs_error_s=dict(median=float((ho.ho_pred - ho.ho_true).abs().median()) if len(ho) else None),
        type_confusion=pd.crosstab(df.type_true, df.type_pred).to_dict() if df.type_ok.notna().any() else {},
    )
    return out, df


def navigation_baseline(trips):
    nav = trips[trips.truth_chooser == "navigation"]
    return dict(
        trips_by_riders_new_to_site=int(len(nav)),
        share_of_all_trips=round(len(nav) / max(len(trips), 1), 4),
        navigation_gate_correct=round(float((nav.truth_chosen == nav.truth_gate).mean()), 4) if len(nav) else None,
        wrong_gate_trips_share=round(float(trips.truth_wrong_gate.mean()), 4),
        wrong_gate_penalty_s=dict(median=float(trips[trips.truth_wrong_gate].truth_wrong_penalty_s.median())
                                  if trips.truth_wrong_gate.any() else None),
    )


def ab_sync(test: pd.DataFrame, profiles: dict, truths: dict, lead_override: dict | None = None):
    """Replay test-period orders with and without DropSync (see module docstring).
    lead_override: per-site come-down lead (s) to use instead of the profile's
    history-based one (the 'after feedback' variant)."""
    site_pen = test[test.truth_wrong_gate].groupby("site_id").truth_wrong_penalty_s.mean().to_dict()
    glob_pen = float(test[test.truth_wrong_gate].truth_wrong_penalty_s.mean()) if test.truth_wrong_gate.any() else 0.0
    recs = []
    for r in test.itertuples(index=False):
        p = profiles.get(r.site_id)
        htype = r.truth_handover_type
        base_end = r.delivered_ts
        base_ho = base_end - r.truth_boundary_ts
        base_wait = (base_end - r.truth_rider_at_hp_ts - 10.0) if htype != "doorstep" else 0.0
        base_call = htype != "doorstep"
        shift = 0.0
        hint_used = False
        if p and p["show_gate_hint"] and r.truth_chooser == "navigation":
            hint_used = True
            g = p["gate_day"]
            if p.get("gate_night") and is_night(r.hour):
                g = p["gate_night"]
            if g["ap_id"] == r.truth_gate:
                shift = -r.truth_wrong_penalty_s
            elif g["ap_id"] != r.truth_chosen:
                shift = -r.truth_wrong_penalty_s + site_pen.get(r.site_id, glob_pen)
        rider_hp = r.truth_rider_at_hp_ts + shift
        drive_end = r.truth_drive_end_ts + shift
        synced = bool(p and p["show_sync"] and htype != "doorstep")
        if htype == "doorstep":
            end = base_end + shift
            wait = 0.0
            cwait = 0.0
            call = False
        elif synced:
            L = (lead_override or {}).get(r.site_id, p["come_down_lead_s"])
            post = p.get("park_to_handover_point_s") or 0.0
            sf = r.truth_speed_factor
            if L > post:
                t_notify = drive_end - (L - post) / sf
            else:
                t_notify = drive_end + (post - L)
            t_notify = max(t_notify, r.assigned_ts)
            if r.truth_notif_ignored:
                cust = rider_hp + r.truth_call_s + r.truth_cust_lead_s
                call = True
            else:
                cust = t_notify + r.truth_cust_lead_s
                call = False
            end = max(rider_hp, cust) + 10.0
            wait = max(0.0, cust - rider_hp)
            cwait = max(0.0, rider_hp - cust)
        else:
            end = rider_hp + r.truth_call_s + r.truth_cust_lead_s + 10.0
            wait = end - rider_hp - 10.0
            cwait = 0.0
            call = True
        recs.append(dict(site_id=r.site_id, htype=htype, synced=synced, hint_used=hint_used,
                         base_ho=base_ho, ds_ho=end - r.truth_boundary_ts,
                         base_wait=base_wait, ds_wait=wait, ds_cust_wait=cwait,
                         base_call=base_call, ds_call=call, ignored=bool(r.truth_notif_ignored)))
    d = pd.DataFrame(recs)

    def summ(x):
        if not len(x):
            return None
        return dict(
            orders=int(len(x)),
            handover_time_s=dict(today_median=round(float(x.base_ho.median()), 1), dropsync_median=round(float(x.ds_ho.median()), 1),
                                 today_mean=round(float(x.base_ho.mean()), 1), dropsync_mean=round(float(x.ds_ho.mean()), 1)),
            rider_wait_at_handover_s=dict(today_median=round(float(x.base_wait.median()), 1),
                                          dropsync_median=round(float(x.ds_wait.median()), 1),
                                          today_mean=round(float(x.base_wait.mean()), 1),
                                          dropsync_mean=round(float(x.ds_wait.mean()), 1)),
            customer_wait_at_handover_s=dict(dropsync_median=round(float(x.ds_cust_wait.median()), 1),
                                             dropsync_p80=round(float(x.ds_cust_wait.quantile(.8)), 1)),
            call_rate=dict(today=round(float(x.base_call.mean()), 4), dropsync=round(float(x.ds_call.mean()), 4)),
            rider_minutes_saved_per_order=round(float((x.base_ho - x.ds_ho).mean() / 60), 3),
        )

    lg = d[d.htype.isin(["lobby", "gate"])]
    out = dict(
        all_orders=summ(d),
        lobby_gate_orders=summ(lg),
        synced_orders=summ(d[d.synced]),
        hint_used_orders=summ(d[d.hint_used]),
        nudge_followed_rate=round(float(1 - d[d.synced].ignored.mean()), 4) if d.synced.any() else None,
        histogram=dict(
            bins_s=list(range(0, 901, 60)),
            today=np.histogram(lg.base_ho.clip(0, 899), bins=range(0, 901, 60))[0].tolist() if len(lg) else [],
            dropsync=np.histogram(lg.ds_ho.clip(0, 899), bins=range(0, 901, 60))[0].tolist() if len(lg) else []),
    )
    return out, d


def pin_fixer(world, evidence: dict, trips: pd.DataFrame, profiles: dict):
    """Lobby sites: flag the pin when the rider's handover stop is at a different
    tower than the one the pin is on (or the pin is on no tower at all)."""
    from shapely.geometry import Point
    truth = trips.set_index("trip_id").truth_pin_wrong.to_dict()
    tp = fp = fn = tn = 0
    for sid, evs in evidence.items():
        p = profiles.get(sid)
        if not p or (p.get("handover") or {}).get("type") != "lobby":
            continue
        towers = world.sites[sid].towers

        def tower_of(xy):
            pt = Point(xy)
            d = [(t.footprint.distance(pt), t.tower_id) for t in towers]
            return min(d)
        for e in evs:
            if e.final_xy is None or e.trip_id not in truth:
                continue
            d_pin, t_pin = tower_of(e.pin_xy)
            _, t_hand = tower_of(e.final_xy)
            flag = d_pin > PIN_OFF_TOWER_M or t_pin != t_hand
            t = truth[e.trip_id]
            tp += flag and t
            fp += flag and not t
            fn += (not flag) and t
            tn += (not flag) and not t
    return dict(rule=f"lobby sites: flag when the pin is >{PIN_OFF_TOWER_M:.0f} m from every tower or on a "
                     "different tower than the rider's handover stop",
                precision=round(tp / (tp + fp), 4) if tp + fp else None,
                recall=round(tp / (tp + fn), 4) if tp + fn else None, flagged=tp + fp, evaluated=tp + fp + fn + tn)


PIN_OFF_TOWER_M = 10.0


def learning_curve(world, evidence: dict, truths: dict, ks=(3, 5, 10, 20, 40, 80), reps=3, seed=11):
    rng = np.random.default_rng(seed)
    rows = []
    for k in ks:
        accs, taccs = [], []
        for _ in range(reps):
            for sid, evs in evidence.items():
                if len(evs) < max(ks):
                    continue
                sub = [evs[i] for i in rng.choice(len(evs), size=k, replace=False)]
                p = build_site_profile(world, world.sites[sid], sub, use_recency=False)
                t = truths[sid]
                if t["n_candidate_gates"] >= 2 and t["changed_gate"] is None:
                    accs.append((p["gate_day"] or {}).get("ap_id") == t["day_gate"])
                taccs.append((p["handover"] or {}).get("type") == t["handover_type"])
        rows.append(dict(trips=k, gate_accuracy_multi_gate=_acc(accs), handover_type_accuracy=_acc(taccs),
                         sites=len([1 for e in evidence.values() if len(e) >= max(ks)])))
    return rows


def recency(world, evidence: dict, truths: dict, eval_day: int):
    """Sites whose rider gate changed permanently on day `rule_change_day`:
    is the profile built at the end of the history pointing at the NEW gate?"""
    out = {}
    for flag in (True, False):
        ok = []
        for sid, evs in evidence.items():
            t = truths[sid]
            if t["changed_gate"] is None:
                continue
            p = build_site_profile(world, world.sites[sid], evs, use_recency=flag)
            ok.append((p["gate_day"] or {}).get("ap_id") == _site_truth_at(t, eval_day, False))
        out["with_recency" if flag else "without_recency"] = _acc(ok)
        out["sites"] = len(ok)
    return out


def robustness(world, noise, site_ids, orders=60, workers=12):
    rows = []
    for scale, interval in [(1, 5), (1, 10), (1, 15), (1, 20), (1, 30), (2, 15), (3, 15)]:
        sim = replace(SIM, ping_interval_s=float(interval), rule_change_prob=0.0, night_gate_change_prob=0.0)
        nz = json.loads(json.dumps(noise))
        nz["stationary"]["sigma_per_axis_m"] *= scale
        S = Simulator(world, sim, nz)
        truths, trips, pings = S.simulate(site_ids=site_ids, orders_override=orders, workers=workers)
        profs = build_profiles(world, trips, pings)
        g = [(p["gate_day"] or {}).get("ap_id") == truths[s]["day_gate"] for s, p in profs.items()
             if truths[s]["n_candidate_gates"] >= 2]
        ty = [(p["handover"] or {}).get("type") == truths[s]["handover_type"] for s, p in profs.items()]
        rows.append(dict(noise_sigma_m=round(nz["stationary"]["sigma_per_axis_m"], 2), noise_scale=scale,
                         ping_interval_s=interval, sites=len(profs),
                         gate_accuracy_multi_gate=_acc(g), handover_type_accuracy=_acc(ty)))
        print("  robustness", rows[-1])
    return rows


def sizing(min_saved: float | None):
    """PDF 2.2: Blinkit 36 lakh orders/day x share x minutes x Rs 2/min x 365."""
    if min_saved is None:
        return None
    orders = 3_600_000
    res = {}
    for share in (0.20, 0.30):
        mins = orders * share * min_saved
        res[f"share_{int(share*100)}pct"] = dict(rider_minutes_per_day=round(mins), rupees_crore_per_year=round(mins * 2 * 365 / 1e7, 1))
    return dict(minutes_saved_per_lobby_gate_order_simulated=round(min_saved, 3), **res,
                note="Simulated minutes replace the PDF's 1.0 / 0.5 assumption; orders, share and Rs 2/min are the PDF's inputs.")


def main(fast: bool = False):
    t0 = time.time()
    world = load_world()
    noise = load_noise()
    truths = json.loads((SIM_DIR / "truth_sites.json").read_text())
    trips = pd.read_parquet(SIM_DIR / "trips.parquet")
    pings = pd.read_parquet(SIM_DIR / "pings.parquet")
    train = trips[trips.day < TRAIN_DAYS]
    test = trips[trips.day >= TRAIN_DAYS]
    t_ref = (BASE.timestamp() + TRAIN_DAYS * 86400)
    print(f"[eval] train {len(train)} trips, test {len(test)} trips")
    profiles, evidence = build_profiles(world, train, pings, t_ref=t_ref, return_evidence=True)
    acc, acc_df = profile_accuracy(world, profiles, truths, train, TRAIN_DAYS)
    # honesty check: the trip-level model was trained on simulated trips of some buildings;
    # report the profile accuracy separately for buildings it never saw.
    try:
        from .entry_model import _split_sites, load_model
        if load_model() is not None:
            _, held = _split_sites(world, Simulator(world, SIM, noise))
            h = acc_df[acc_df.site_id.isin(set(held))]
            acc["held_out_buildings"] = dict(
                sites=int(len(h)), gate_accuracy_multi_gate=_acc(h[h.n_gates >= 2].gate_ok),
                gate_hint_precision=_acc(h[h.gate_shown].gate_ok), gate_hint_coverage=round(float(h.gate_shown.mean()), 4),
                handover_type_accuracy=_acc(h.type_ok))
    except Exception as ex:  # never block the evaluation on this extra
        acc["held_out_buildings"] = dict(error=repr(ex))
    print("[eval] accuracy", json.dumps({k: v for k, v in acc.items() if k != "type_confusion"}))
    ab, ab_df = ab_sync(test, profiles, truths)
    # 'After feedback' variant: once the sync is live, the time from the 'Coming' tap to the
    # customer reaching the handover point is observed directly; its per-site median
    # (from the training-period orders) replaces the history-based lead time.
    fb = train[train.truth_handover_type.isin(["lobby", "gate"])].groupby("site_id").truth_cust_lead_s.median().to_dict()
    ab_fb, _ = ab_sync(test, profiles, truths, lead_override=fb)
    ab["after_feedback"] = dict(lobby_gate_orders=ab_fb["lobby_gate_orders"], synced_orders=ab_fb["synced_orders"],
                                note="lead time = median observed 'Coming' tap -> customer at handover point")
    # Recency test needs the post-change trips: learn on the full history, score against
    # the gate in force on the last day.
    _, evidence_all = build_profiles(world, trips, pings, return_evidence=True)
    print("[eval] A/B lobby+gate", json.dumps(ab["lobby_gate_orders"]))
    res = dict(
        source="simulated delivery history on real OSM map with GPS noise measured from real Indian OSM traces",
        assumptions=sim_assumptions_dict(),
        split=dict(train_days=f"0-{TRAIN_DAYS-1}", test_days=f"{TRAIN_DAYS}-{SIM.days-1}",
                   train_trips=int(len(train)), test_trips=int(len(test))),
        profile_accuracy=acc,
        baselines=navigation_baseline(train),
        recency=recency(world, evidence_all, truths, SIM.days - 1),
        pin_fixer=pin_fixer(world, evidence, train, profiles),
        ab_sync=ab,
        sizing=sizing((ab["lobby_gate_orders"] or {}).get("rider_minutes_saved_per_order")),
    )
    print("[eval] learning curve")
    res["learning_curve"] = learning_curve(world, evidence, truths)
    if not fast:
        print("[eval] robustness")
        rng = np.random.default_rng(3)
        multi = sorted(s for s, t in truths.items() if t["n_candidate_gates"] >= 2)
        pick = list(rng.choice(multi, size=min(25, len(multi)), replace=False))
        res["robustness"] = robustness(world, noise, pick, workers=int(os.environ.get("DROPSYNC_WORKERS", "12")))
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "metrics.json").write_text(json.dumps(res, indent=2, default=float))
    acc_df.to_csv(EVAL_DIR / "site_accuracy.csv", index=False)
    print(f"[eval] done in {time.time()-t0:.0f}s -> {EVAL_DIR/'metrics.json'}")
    return res


if __name__ == "__main__":
    import sys
    main(fast="--fast" in sys.argv)
