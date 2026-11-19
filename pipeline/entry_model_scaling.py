"""Does MORE augmented data make the trip-level model better?

Generates 18 randomised simulation setups (the first 6 are the ones the shipped model used),
trains on the first 6 / 12 / 18, and scores every version on the SAME held-out buildings
under the same test conditions. Output: data/eval/entry_model_scaling.json
Usage: python -m pipeline.entry_model_scaling
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import replace

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from .config import EVAL_DIR, SIM
from .entry_model import FEATURES, EntryModel, _rows_for, _split_sites, generate, score
from .simulate import Simulator, load_noise, load_world


def main():
    t0 = time.time()
    world, noise = load_world(), load_noise()
    workers = int(os.environ.get("DROPSYNC_WORKERS", "16"))
    train_sites, test_sites = _split_sites(world, Simulator(world, SIM, noise))
    print(f"[scaling] generating 18 augmented setups on {len(train_sites)} training buildings", flush=True)
    trips, pings = generate(world, noise, train_sites, n_configs=18, orders_per_site=40, workers=workers)
    rows = _rows_for(world, trips, pings)
    rows["config"] = rows.trip_id.str.extract(r"-c(\d+)$")[0].astype(int)
    print(f"[scaling] {trips.trip_id.nunique()} trips, {len(rows)} rows ({time.time() - t0:.0f}s)", flush=True)

    tests = [("normal", replace(SIM, seed=900), 1.0),
             ("closures + new riders", replace(SIM, seed=901, new_to_site_share=0.5, rule_change_prob=0.6,
                                               wrong_gate_admitted_prob=0.0), 1.0),
             ("2x GPS noise", replace(SIM, seed=902, new_to_site_share=0.4), 2.0),
             ("sparse pings (30 s)", replace(SIM, seed=903, ping_interval_s=30.0, new_to_site_share=0.4), 1.0)]
    test_sets = []
    for name, sim, scale in tests:
        nz = json.loads(json.dumps(noise))
        nz["stationary"]["sigma_per_axis_m"] *= scale
        _, tt, tp = Simulator(world, sim, nz).simulate(site_ids=test_sites, orders_override=40, workers=workers)
        test_sets.append((name, tt, _rows_for(world, tt, tp)))

    results = []
    for n_cfg in (6, 12, 18):
        sub = rows[rows.config < n_cfg]
        X = sub[FEATURES].to_numpy()
        m = EntryModel(
            HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=0).fit(X, sub.y_entry),
            HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=0,
                                           class_weight="balanced").fit(X, sub.y_refused))
        row = dict(setups=n_cfg, trips=int(sub.trip_id.nunique()))
        for name, tt, tr in test_sets:
            pred = {}
            for tid, grp in tr.groupby("trip_id"):
                site = world.sites[grp.site_id.iloc[0]]
                rws = [(next(a for a in site.aps if a.ap_id == r.ap_id), {k: getattr(r, k) for k in FEATURES})
                       for r in grp.itertuples()]
                ent, _, refs = m.predict_trip(rws)
                pred[tid] = (ent.ap_id if ent else None, {a.ap_id for a in refs})
            s = score(tt, pred)
            row[name] = dict(entry=s["entry_accuracy"], refusal_recall=s["refusal_recall"],
                             refusal_precision=s["refusal_precision"])
        results.append(row)
        print("[scaling]", json.dumps(row), flush=True)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "entry_model_scaling.json").write_text(json.dumps(dict(
        held_out_buildings=len(test_sites), results=results, seconds=round(time.time() - t0)), indent=2))
    print(f"[scaling] done in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
