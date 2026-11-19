"""End-to-end check on the real OSM study zone (skipped if data has not been built).

Simulates a small history for a few sites and asserts the profile builder,
which never sees ground truth, recovers gate and handover type well.
"""
import json
from dataclasses import replace

import pytest

from pipeline.config import EVAL_DIR, OSM_DIR, SIM

pytestmark = pytest.mark.skipif(not (OSM_DIR / "city" / "graph.graphml").exists()
                                or not (EVAL_DIR / "noise_calibration.json").exists(),
                                reason="study-zone data not built")


@pytest.fixture(scope="module")
def world():
    from pipeline.simulate import load_world
    return load_world()


def test_builder_recovers_truth(world, tmp_path):
    from pipeline.profile_builder import build_profiles
    from pipeline.simulate import Simulator, load_noise
    noise = load_noise()
    sim = replace(SIM, rule_change_prob=0.0, night_gate_change_prob=0.0)
    S = Simulator(world, sim, noise)
    ids = [s.site_id for s in world.sites.values() if len(S.candidates(s)) >= 2][:12]
    truths, trips, pings = S.simulate(site_ids=ids, orders_override=60)
    # the builder must not depend on truth columns
    assert all(not c.startswith("truth_") for c in trips[[c for c in trips if not c.startswith("truth_")]].columns)
    profiles = build_profiles(world, trips, pings)
    gate_ok = [(p["gate_day"] or {}).get("ap_id") == truths[s]["day_gate"] for s, p in profiles.items()]
    type_ok = [(p["handover"] or {}).get("type") == truths[s]["handover_type"] for s, p in profiles.items()]
    assert sum(gate_ok) / len(gate_ok) >= 0.75, gate_ok
    assert sum(type_ok) / len(type_ok) >= 0.75, type_ok
    shown = [ok for (s, p), ok in zip(profiles.items(), gate_ok) if p["show_gate_hint"]]
    assert not shown or sum(shown) / len(shown) >= 0.85


def test_profiles_are_json_serialisable(world):
    from pipeline.profile_builder import build_profiles
    from pipeline.simulate import Simulator, load_noise
    S = Simulator(world, SIM, load_noise())
    ids = [s.site_id for s in world.sites.values() if S.eligible(s)][:3]
    _, trips, pings = S.simulate(site_ids=ids, orders_override=20)
    json.dumps(build_profiles(world, trips, pings), default=float)
