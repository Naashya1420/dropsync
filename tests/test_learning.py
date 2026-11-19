"""Learning behaviour on a building the trip-level model never saw (Spring Beauty, held out):
  * cold start: the right gate is shown within 10 deliveries;
  * a gate closes: DropSync stops recommending it within 10 deliveries and never records the
    turned-away riders as entries through the closed gate.
Skipped until the study-zone data and the trained entry model exist."""
import math
from dataclasses import replace

import pytest

from pipeline.config import EVAL_DIR, OSM_DIR, SIM
from pipeline.entry_model import MODEL_PATH

pytestmark = pytest.mark.skipif(not (OSM_DIR / "city" / "graph.graphml").exists() or not MODEL_PATH.exists()
                                or not (EVAL_DIR / "noise_calibration.json").exists(), reason="data/model not built")
SITE = "way/41748192"


@pytest.fixture(scope="module")
def env():
    from pipeline.simulate import Simulator, load_noise, load_world
    w = load_world()
    noise = load_noise()
    site = w.sites[SITE]
    c = Simulator(w, SIM, noise).candidates(site)
    A = c[0]
    B = max(c[1:], key=lambda b: math.dist((b.x, b.y), (A.x, A.y)))
    return w, noise, site, A, B


def _run(env, patch, sim, n):
    from pipeline.simulate import Simulator
    w, noise, site, A, B = env
    S = Simulator(w, sim, noise)
    base = S.make_truth(site)
    S.make_truth = lambda s: {**base, **patch, "towers": base["towers"]}
    _, trips, pings = S.simulate_site(site.site_id, orders_override=n)
    return trips.sort_values("assigned_ts").reset_index(drop=True), pings


def test_cold_start_hint_within_10(env):
    from pipeline.profile_builder import build_profiles
    w, noise, site, A, B = env
    sim = replace(SIM, night_gate_change_prob=0, rule_change_prob=0)
    trips, pings = _run(env, dict(day_gate=A.ap_id, night_gate=A.ap_id, changed_gate=None, change_day=None,
                                  handover_type="lobby"), sim, 20)
    p = build_profiles(w, trips.iloc[:10], pings)[SITE]
    assert p["show_gate_hint"] and p["gate_day"]["ap_id"] == A.ap_id


def test_gate_closure_switch_within_10(env):
    import pandas as pd
    from pipeline.profile_builder import build_profiles
    w, noise, site, A, B = env
    sim = replace(SIM, night_gate_change_prob=0, rule_change_prob=0, wrong_gate_admitted_prob=0.0,
                  stale_memory_days=14, stale_memory_prob=0.5)
    trips, pings = _run(env, dict(day_gate=A.ap_id, night_gate=A.ap_id, changed_gate=B.ap_id, change_day=45,
                                  handover_type="lobby"), sim, 200)
    pre, post = trips[trips.day < 45], trips[trips.day >= 45]
    p = build_profiles(w, pd.concat([pre, post.iloc[:10]]), pings)[SITE]
    assert p["gate_day"]["ap_id"] != A.ap_id          # the closed gate is no longer recommended
    _, ev = build_profiles(w, post, pings, return_evidence=True)
    detours = set(post[post.truth_wrong_gate].trip_id)
    wrong = [e for e in ev[SITE] if e.trip_id in detours and e.cross_xy and math.dist(e.cross_xy, (A.x, A.y)) < 30]
    assert not wrong                                   # turned-away riders are not 'entries' at A
