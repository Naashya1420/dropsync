# DropSync — building-aware handover coordination (Eternal Hackathon, team CosmicBlunder)

DropSync learns a profile for every society, office park and mall from past deliveries
(rider entry gate, parking point, handover rule, typical handover time) and uses it to
send the customer **one** "come down now" nudge timed so customer and rider reach the
handover point together. No hardware, no new rider data entry.

This repository is the working prototype promised in the problem statement (§4.3):

| Promised deliverable | Where |
|---|---|
| Profile builder on GPS traces: stop detection, clustering, gate + handover-type inference, confidence | `pipeline/` (`stops.py`, `profile_builder.py`) |
| Rider app screen: building card with gate, parking, handover rule, live customer status | Web app → **Live demo**, left phone |
| Customer app screen: timed "come down now" + one-tap replies + checkout expectation banner | Web app → **Live demo**, right phone |
| Ops dashboard: map of building profiles + trial metrics | Web app → **Ops dashboard** |
| Real-time trigger service | `backend/` (FastAPI + WebSocket) |
| Building profile store | PostGIS (`docker-compose.yml`, `pipeline/db.py`), JSON fallback |
| Campus field trial (IIIT Allahabad) | Web app → **Field trial** logger, `pipeline/field.py` |
| **DropSync inside the delivery-partner app** (concept) | `/rider` (rider phone), `/track` (customer phone), `/stage` (both side by side) |

Also built from §3.3: pin fixer, fair-lateness evidence, per-building ETA correction,
new-partner mode, rider "did this help?" feedback, night-time gate.

### DropSync inside the delivery-partner app

`/rider` is a full-screen phone app that follows the stages delivery-partner apps are publicly
known to use: go online → order request → reach restaurant → picked up → reach customer →
delivered, with slide-to-confirm actions, navigation and call buttons. DropSync lives *inside*
those stages rather than as a separate screen:

| Stage | What DropSync adds |
|---|---|
| Order request | A DropSync badge on the drop: handover rule plus whether the rider gate is known |
| Drive to customer | **Building guide**: rider gate named by its real OSM road ("Gate on Hoodi Main Road"), learned parking spot, handover rule, usual handover time. New-partner banner on first visits. |
| Drive to customer | **Live customer strip**: "will be told to come down X min before you arrive" → "Coming down" / "2 more minutes" / "Leave with security" → "at the handover point" (no call needed) |
| Delivered | Fair-lateness check with evidence, plus "Did the building guide help?" (feeds re-learning) |

Pickups are real OSM restaurants in the zone (218 named restaurants, cafés and fast-food
outlets). The app has English and Hindi. `/track` is the customer's phone: tracking, the single
come-down push with one-tap replies, and "I'm at the lobby". Open both on two phones, or `/stage`
on a laptop.

The screens follow **real reference screens** of the delivery-partner apps: the official Play Store
listings and public rider tutorial videos (Feed, New order, order list). The layout and sampled colours
match those references; there is no Zomato or Blinkit logo or wordmark, and it's labelled a concept.
Sources and colours: `ref/SOURCES.md`.

---

## Data — India only

No public Indian last-mile dataset contains delivery GPS **and** delivery events
(Indian food-delivery traces used in research are licensed; Kaggle "food delivery"
sets have only coordinates and total time). LaDe (China) is not used at all.
So every source is Indian and labelled by what it is:

| Source | Real? | Used for |
|---|---|---|
| **OpenStreetMap, Geofabrik India extract** (`india-261117.osm.pbf`, data to 2026-11-17) | real | site boundaries, gates/entrances, parking, buildings + floor counts, road & path network |
| **OpenStreetMap public GPS traces** for the study zone (OSM API) | real | measuring GPS error: jitter, its autocorrelation, spike rate, distance from roads |
| **Simulated delivery history** on that real map | simulated | ground truth is known, so gate / handover-rule accuracy and the sync A/B can be *measured*; all behaviour parameters are explicit (`pipeline/config.py::SimAssumptions`) |
| **Campus field trial** (phone GPS via the web logger) | real | measured Indian numbers: gate inference from GPS, rider wait with vs without sync |

### Why Bengaluru (Whitefield–Brookefield–ITPL)

Chosen by measurement (`pipeline/city_select.py` → `data/eval/city_comparison.json`):
an identical 0.30° box around 10 metros, counting societies / office parks / malls that have
≥2 OSM gates on their boundary (gate choice only matters there). Bengaluru leads clearly
(2,140 vs Delhi 1,499, Mumbai 1,036, Pune 980, Gurugram 709). The study zone is the 3 km
window (one dark-store area) with the most such sites: 92 residential societies and 85 office
parks, 627 mapped gates.

---

## How it works

```
OSM India extract ──► sites, gates, parking, buildings, road graph ─┐
OSM public traces ──► measured GPS noise model ────────────────────┤
                                                                    ▼
delivery history (GPS pings + assigned/arrived/delivered) ──► PROFILE BUILDER (nightly, per site)
   1 clean pings (accuracy ≤30 m, no >25 m/s jumps)                  │
   2 stops: ≥60 s within 25 m                                         │
   3 entry = first sustained outside→inside crossing (3-fix majority  │
     filter), each entry votes for the nearest OSM access point;      │
     entries far from any mapped gate are DBSCAN-clustered as         │
     "learned gates" OSM lacks; winner = where FAST trips enter       │
   4 handover rule: no GPS fix ≥45 s before 'delivered' near a        │
     building = doorstep; final wait outside/at the edge = gate;      │
     final wait inside = lobby                                        │
   5 night (23–06) gate when it differs                               │
   6 confidence: high ≥40 trips & ≥75% agree, medium ≥12 & ≥60%;      │
     hints only at ≥ medium and only if that gate is faster           │
   recency weight 0.5^(age/30 days)                                   ▼
                                                 profiles (PostGIS / JSON)
                                                                    │
REAL-TIME SERVICE (FastAPI) ◄────────────────────────────────────────┘
   on assignment: building card to rider, banner/ETA at checkout
   on each rider location: ETA to handover point (OSM routing)
   when ETA ≤ building's come-down lead time (adjusted by tower floors): ONE push
   customer taps Coming / Leave with security / 2 more minutes → rider card
   on delivery: outcome logged; fair-lateness evidence attached
```

---

## Run it

### Demo (laptop)

```bash
cd dropsync
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
.venv/bin/uvicorn backend.app:app --port 8000
# open http://localhost:8000/stage  (rider app + customer phone side by side)
#      http://localhost:8000/rider and /track on two phones; /ops; /trial
```
`data/out`, `data/eval` and `data/osm/city/graph.graphml` are what the demo needs; they are
produced by the pipeline below.

Optional PostGIS store: `docker compose up -d`, then
`DATABASE_URL=postgresql://dropsync:dropsync@localhost:5433/dropsync .venv/bin/python -m pipeline.db`
and start the API with the same `DATABASE_URL` (it falls back to JSON if the DB is down).

Real phones on the same Wi-Fi: the API listens on localhost only by default. To let phones
reach it, start it with `--host 0.0.0.0` (this exposes it to everyone on that network; use only
on a network you trust), then open `http://<laptop-ip>:8000/rider` and `/track`.
Field trial (GPS needs HTTPS): `cd web && npm run dev:https`, open the
`https://<laptop-ip>:5173/trial` address on the phone, keep the API running on :8000.

### Pipeline

```bash
# osmium-tool: native, or `docker build -t dropsync-osmium docker/osmium`
curl -L -o data/raw/india-latest.osm.pbf https://download.geofabrik.de/asia/india-latest.osm.pbf
./run_pipeline.sh data/raw/india-latest.osm.pbf
pytest -q
```

---

## Results

All numbers come from `data/eval/metrics.json` (simulated history) and
`data/eval/noise_calibration.json` (real traces). They're regenerated by `./run_pipeline.sh`.

### Measured from real Indian GPS (OSM public traces, Whitefield zone)

| | |
|---|---|
| Points / segments / years | 670,096 / 41,236 / 2023–2026 |
| Stationary jitter | median 3.1 m, p95 17.9 m; RMS σ = 5.6 m per axis (used in simulation, so the simulation is noisier than typical) |
| Error autocorrelation | ρ = 0.987 per second |
| Spikes (> 25 m/s jumps) | 0.07 % of fixes |
| Distance of moving fixes from mapped roads | median 2.0 m, p90 5.4 m |
| Sampling interval | median 15 s (used as the simulated ping rate) |

### Profile accuracy (out of sample: learned on days 0–59, 9,915 trips, 151 real sites)

| Metric | Result |
|---|---|
| Rider gate hint precision (only when shown) | **94 %** (shown at 72 % of sites) |
| Gate a rider new to the building picks via navigation (baseline) | 76 % right |
| Rider gate, all sites / sites with ≥ 2 entries | 91 % / 81 % |
| Gate accuracy vs trips per building (multi-gate sites) | 95 % at 3 trips, **100 % from 10 trips** |
| Handover rule (all / where shown at checkout, 95 % of sites) | 92 % / **95 %** |
| Parking point error | median 4 m, p80 7 m |
| Handover-time estimate error | median 5 s |
| Night-only gate | 50 % found at the 4 sites with ≥ 6 night trips; 8 % over all 24 (data-limited); 0 false alarms |
| Gate changed mid-history (6 sites) | 4 of 6 right after the change (14-day change detector) |
| Pin fixer (lobby sites, single order) | precision 56 %, recall 62 % |
| Robustness | gate 84–96 % for pings every 5–30 s; at 2× / 3× the measured noise, handover rule falls to 80 % / 36 % |

### Come-down sync A/B (out of sample: days 60–89, 4,048 lobby/gate orders replayed both ways)

| | Today | DropSync | DropSync after feedback¹ |
|---|---|---|---|
| Handover time (site boundary → delivered), median | 6.8 min | **3.4 min** | 3.5 min |
| Rider wait at handover point, median / mean | 3.8 / 4.1 min | **0 / 1.0 min** | 0 / 1.1 min |
| Customer wait at handover point, median (p80) | — | 1.1 min (2.3) | **3 s** (1.1 min) |
| Orders needing a rider–customer call | 100 % | **19 %** | 19 % |
| Rider-minutes saved per lobby/gate order | | **3.2** | 3.1 |

¹ The lead time is re-learned from the observed "Coming" tap → customer-at-handover time once the sync is live (PDF §4.6).
85 % of nudges are followed (15 % ignored by assumption, with a fallback call).

**What these depend on.** The *today* arm assumes customers start coming down only after
the rider's call (PDF §1.1). The *map* is real and the *GPS noise* is measured. Customer
come-down times (lift wait, floors, readiness), the handover-rule mix and guard behaviour are
assumptions listed in `pipeline/config.py`. With 3.2 simulated minutes, the PDF's §2.2
formula gives ₹168–252 crore/yr for Blinkit alone, but that inherits every assumption above.
**The campus field trial is how to replace it with a measured number.**

### What's real vs simulated, in one line

The map, the gates, the floors and the GPS noise are real. The delivery history is simulated
on top of them so ground truth is known. The campus trial adds real Indian measurements.

---

## Repository map

```
pipeline/   city_select · extract_cities · osm_extract · traces · noise · sitemodel
            simulate · stops · profile_builder · evaluate · publish · db · field · config
backend/    app.py (FastAPI REST + WebSocket) · realtime.py (trigger, routing, fair lateness)
web/        React + Leaflet + Recharts: rider app (/rider, src/rider/) · customer phone (/track) ·
            stage (/stage) · Live demo · Ops dashboard · Field trial logger
tests/      stops · end-to-end on real zone · API order flow · rider-app flow · field analysis
docker/     osmium-tool image   docker-compose.yml  PostGIS
WORKLOG.md  decisions, numbers and history of the build
```
