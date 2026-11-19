"""Single place for study-area settings and every simulation assumption.

Anything marked ASSUMPTION is not measured; it is a parameter of the simulated
delivery history and is reported as such in the evaluation outputs. The campus
field trial (data/field) replaces these with measured values.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
OSM_DIR = DATA / "osm"
TRACES_DIR = DATA / "traces"
SIM_DIR = DATA / "sim"
OUT_DIR = DATA / "out"
EVAL_DIR = DATA / "eval"
FIELD_DIR = DATA / "field"

USER_AGENT = "dropsync-prototype/0.1 (hackathon research)"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


@dataclass(frozen=True)
class StudyArea:
    key: str
    city: str
    label: str
    # south, west, north, east
    bbox: tuple[float, float, float, float]
    why: str


# Chosen from a measured comparison of OSM coverage across Indian metros
# (see data/eval/city_comparison.json and README "Why this city").
STUDY = StudyArea(
    key="__set_by_city_selection__",
    city="",
    label="",
    bbox=(0.0, 0.0, 0.0, 0.0),
    why="",
)

CAMPUS = StudyArea(
    key="iiita",
    city="Prayagraj",
    label="IIIT Allahabad campus (field trial)",
    bbox=(25.4250, 81.7640, 25.4350, 81.7790),
    why="Team's campus; field trial site named in the PDF (section 4.4).",
)


@dataclass
class SimAssumptions:
    """Parameters of the simulated delivery history (all ASSUMPTIONS)."""
    seed: int = 7
    days: int = 90
    # Delivery-partner GPS sampling interval while on an order. Eternal does not publish
    # it; default = the MEASURED median interval of real OSM traces in the study zone
    # (15 s, data/eval/noise_calibration.json). Robustness is evaluated at 5-30 s.
    ping_interval_s: float = 15.0
    rider_speed_kmh_road: float = 18.0      # 2-wheeler in city traffic incl. signals
    rider_speed_kmh_inside: float = 10.0    # inside a gated site (speed breakers, guards)
    walk_speed_mps: float = 1.2             # pedestrian walking speed (common planning value)
    approach_radius_m: float = 1500.0       # simulate the final ~1.5 km of each trip
    # Handover-type mix for residential sites (gate, lobby, doorstep)
    residential_handover_mix: tuple[float, float, float] = (0.15, 0.45, 0.40)
    # Commercial / office sites: reception or gate handover dominates
    commercial_handover_mix: tuple[float, float, float] = (0.35, 0.55, 0.10)
    night_gate_change_prob: float = 0.35    # site uses a different rider gate 23:00-06:00
    rule_change_prob: float = 0.10          # rider gate permanently changes on day `rule_change_day`
    rule_change_day: int = 60
    riders: int = 400                        # rider ids in the zone (labels only)
    # Share of trips made by a rider who has not delivered to this building before.
    # Set to the monthly new-partner share: ~1.5-2 lakh of 7-8 lakh partners join each
    # month (PDF ref [1]) -> ~22%. Conservative: experienced riders also meet new buildings.
    # New riders pick the gate navigation would (min road distance + straight line to pin).
    new_to_site_share: float = 0.22
    stale_memory_days: int = 14              # after a gate change, experienced riders may use the old gate...
    stale_memory_prob: float = 0.5           # ...with this probability, for this many days
    wrong_gate_admitted_prob: float = 0.35   # guard lets a rider in through the wrong gate after a delay
    wrong_gate_argue_s: tuple[float, float] = (40.0, 150.0)
    floors_default_residential: tuple[int, int] = (4, 22)
    floors_default_commercial: tuple[int, int] = (3, 15)
    floor_height_m: float = 3.0
    lift_speed_mps: float = 1.0              # typical residential passenger lift
    lift_wait_s: tuple[float, float] = (20.0, 120.0)
    doorstep_handover_s: tuple[float, float] = (20.0, 60.0)
    # Customer behaviour without DropSync: comes down only after the rider calls on arrival
    call_connect_s: tuple[float, float] = (20.0, 75.0)
    customer_ready_s: tuple[float, float] = (15.0, 90.0)   # time to put on shoes, find phone, leave the flat
    # With DropSync sync notification
    notif_ignore_prob: float = 0.15          # customer does not react; rider falls back to a call
    pin_wrong_prob: float = 0.20             # saved pin points at the wrong tower / site centroid
    orders_per_site_range: tuple[int, int] = (40, 400)
    hour_weights: dict = field(default_factory=lambda: {
        # order-hour profile: breakfast, lunch peak, evening snack, dinner peak, late night
        0: 2, 1: 1, 2: 0.5, 3: 0.3, 4: 0.3, 5: 0.5, 6: 1, 7: 2, 8: 3, 9: 3, 10: 3, 11: 4,
        12: 7, 13: 8, 14: 6, 15: 4, 16: 4, 17: 5, 18: 6, 19: 7, 20: 9, 21: 10, 22: 8, 23: 4,
    })


SIM = SimAssumptions()


def load_study() -> StudyArea:
    p = DATA / "study_area.json"
    if p.exists():
        return StudyArea(**{**json.loads(p.read_text()), "bbox": tuple(json.loads(p.read_text())["bbox"])})
    return STUDY


def save_study(area: StudyArea) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "study_area.json").write_text(json.dumps(asdict(area), indent=2))


def sim_assumptions_dict() -> dict:
    return asdict(SIM)
