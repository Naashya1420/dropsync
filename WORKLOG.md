# DropSync: complete progress log and handover

**Team CosmicBlunder (IIIT Allahabad), Eternal Hackathon. Last updated: 19 Nov 2026.**

This file records everything done on the build so far: what exists, how to run it, every decision
and why, the results, what's real vs simulated, the problems hit along the way, and what's left.
Read sections 1–3 first; the rest is reference.

- Project folder (laptop): `/home/aashay/code/eternal/dropsync`
- Problem statement we promised against: `../DropSync_Problem_Statement.pdf`
- Copy on the college server: `gpu80:/DATA/kmpooja/dropsync_eternal/` (see section 12)

---

## 1. Where things stand

**The build is complete. The only remaining work is the campus field trial, which needs people on site.**

| Area | State |
|---|---|
| Dataset research, choice of city and zone | Done: Bengaluru, Whitefield / Brookefield / ITPL |
| Real OpenStreetMap (OSM) map layer for the zone + IIIT-A campus | Done |
| Real GPS noise measured from OSM public traces | Done (670,096 points) |
| Simulated delivery history on the real map | Done (15,034 orders, 151 buildings, 90 days) |
| Profile builder (PDF core feature 1) | Done |
| Out-of-sample evaluation | Done (`data/eval/metrics.json`) |
| PostGIS profile store | Done (JSON fallback if the database is down) |
| Real-time "come down now" service (PDF core feature 2) | Done (FastAPI + WebSocket) |
| **Rider app with DropSync built in** (`/rider`) + customer phone (`/track`) + side-by-side `/stage` | Done |
| Three-panel live demo, Ops dashboard, field-trial logger | Done |
| Tests | 10 passing |
| **Campus field trial at IIIT-A** | **TODO (team)**, see section 11 |
| Delete the gpu80 work folder | Waiting until the teammate has this file (section 12) |

All promised deliverables from PDF §4.3 are built:

| Promised | Where |
|---|---|
| Profile builder on GPS traces (stops, clustering, gate + handover-type inference, confidence) | `pipeline/stops.py`, `pipeline/profile_builder.py` |
| Rider app screen: building card with gate, parking, rule, live customer status | `/rider` (and the left phone in `/`) |
| Customer app screen: timed "come down now", one-tap replies, checkout banner | `/track` (and the right phone in `/`) |
| Ops dashboard: map of profiles + trial metrics | `/ops` |

Extras from PDF §3.3 that are also built: pin fixer, fair-lateness evidence, per-building ETA
correction, new-partner mode, rider "did this help?" feedback, night-time gate, gate-change detection.

---

## 2. How to run the demo (laptop)

Everything needed for the demo is already in `data/` (built map, profiles, metrics).

```bash
cd /home/aashay/code/eternal/dropsync

# one-time setup (already done on Aashay's laptop)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd web && npm install && npm run build && cd ..

# optional: PostGIS store (the API falls back to data/out/profiles.json without it)
docker compose up -d
DATABASE_URL=postgresql://dropsync:dropsync@localhost:5433/dropsync .venv/bin/python -m pipeline.db

# start the service (serves the web app too)
DATABASE_URL=postgresql://dropsync:dropsync@localhost:5433/dropsync .venv/bin/uvicorn backend.app:app --port 8000
```

Then open:

| URL | What it is | Use it for |
|---|---|---|
| **http://localhost:8000/stage** | Only the two phones side by side (rider + customer), no other text | **Main demo for the Eternal team** |
| http://localhost:8000/rider | Delivery-partner app with DropSync inside (full screen) | Open on the "rider" phone |
| http://localhost:8000/track | Customer phone: tracking + the come-down notification | Open on the "customer" phone |
| http://localhost:8000/ | Three-panel demo (rider card · live map · customer) with a DropSync on/off switch | Showing today vs DropSync on one screen |
| http://localhost:8000/ops | Ops dashboard: map of all profiles, metrics, charts, city comparison | Showing the evidence |
| http://localhost:8000/trial | Field-trial GPS logger | Campus trial (needs HTTPS on phones) |

**Demo script for `/stage`:** tap the **Offline** toggle (top-left) to go online → a *New order* arrives in a
few seconds → slide *Accept order* → slide *Reached pickup* → *Order picked up* → the rider sees the **building guide** → the customer
phone receives **one** "please come down now" → tap **Coming** → the rider's screen shows "Coming down"
straight away (no call) → slide *Reached drop location* → *Slide when handed over* → the rider sees the
not-late check and "Did the building guide help?". Tapping the rider's **avatar** ("R", top-right) opens demo settings:
English/हिंदी, **Theme (System/Light/Dark)**, building, tower, replay speed, **DropSync on/off** (off = today's flow),
new-partner mode. Changing the building while a New order is showing replaces it with an order to the new building.

Good demo buildings: **Skylark Esta** (gate handover, 20 floors, 400 trips) and **Bren Avalon** (lobby, 400 trips).

**Using real phones on Wi-Fi:** by default the API only listens on the laptop (localhost). To let phones
connect, start it with `--host 0.0.0.0` and open `http://<laptop-ip>:8000/rider` and `/track`. This exposes
the server to everyone on that network, so do it only on a network you trust. (Claude Code's safety check
blocked doing this automatically on the college Wi-Fi; it's a deliberate choice for the team.)

---

## 2b. Online deployment (phone demo)

- Code: **private GitHub repo https://github.com/Naashya1420/dropsync** (branch `main`).
- Hosting: **Render.com free web service**, built from `Dockerfile` using `render.yaml`
  (region Singapore, health check `/api/health`, auto-deploy on every push to `main`).
- The deployed server is light: only `requirements-deploy.txt` (FastAPI, uvicorn, networkx, numpy) and
  the published data (profiles, metrics, road graph, restaurants, about 11 MB). It reads the road graph without osmnx.
- **Passcode:** set `DROPSYNC_PASSCODE` in Render → service → Environment. Each phone types it once
  (remembered 30 days). `/api/health` stays open for Render's health check. It is never stored in git.
- First-time setup (owner, about 2 min): render.com → sign in with GitHub → **New + → Blueprint** → give Render
  access to `Naashya1420/dropsync` → select it → enter the passcode → **Apply**. The first build takes about 5–10 min.
- The free tier sleeps after 15 min idle: open the link about 1 min before the demo to wake it.
- On phones: rider phone → `https://<your-app>.onrender.com/rider`, customer phone → `/track`
  (or one phone with two tabs). Laptop: `/stage`. Use "Add to Home screen" for a full-screen app feel.
- Data written online (field-trial uploads, live logs) is temporary on the free tier (lost on restart).
- Verified before deploying: the exact files the Dockerfile copies, run with only the deploy dependencies,
  passed the passcode checks and the full rider/customer flow in a browser. (Docker Hub was unreachable
  from the college Wi-Fi, so the image itself is built on Render's servers.)

---

## 3. What DropSync does (one paragraph)

Riders reach the right address but lose minutes in the last 100 m: wrong gate, no parking, unclear
lobby/doorstep rules, and customers who only start coming down after a call. DropSync learns a **profile
per building** from past deliveries (rider entry gate, parking spot, handover rule, typical handover time,
come-down lead time) and uses it to send the customer **one** notification timed so that customer and rider
reach the handover point together. The rider sees a building guide and the customer's live status. No
hardware, no new rider data entry.

---

## 4. Data: everything is Indian, and labelled real or simulated

The Eternal mentors asked us not to use LaDe (China). **LaDe is not used anywhere.**

### 4.1 Search for an Indian delivery dataset (none is public)
- Indian food-delivery GPS used in research (FairFoody; Joshi et al. 2021) is **licensed** from a company, not public.
- The Kaggle "Food Delivery Dataset" (Indian cities) has only restaurant/customer coordinates and total time: no GPS traces, no handover phase.
- The IISc LPG last-mile dataset has customer locations and delivery sequences, no traces.

### 4.2 What "the OSM dataset" turned out to be (tested, not assumed)
OpenStreetMap gives two different things:
1. **Map data** (gates, entrances, building outlines and floor counts, parking, roads, named societies): rich in Indian cities. **Used as the real map.**
2. **Public GPS traces** (real phone/logger tracks uploaded by mappers): real Indian GPS, but **not deliveries**. There are no orders and no arrived/delivered events. In a first Gurugram probe only 7 of 363 site entries were within 15 m of a mapped gate. **Used only to measure GPS noise.**

### 4.3 The final data stack
| Source | Real? | Used for |
|---|---|---|
| OSM India extract from Geofabrik (`india-261117.osm.pbf`, 1.7 GB, MD5-verified, data up to 2026-11-17 21:24 UTC) | real | buildings/sites, gates, parking, floors, road and path network, restaurants |
| OSM public GPS traces in the study zone (670,096 points, 41,236 segments, 2023–2026) | real | GPS noise model |
| Simulated delivery history on the real map | simulated | ground truth is known, so accuracy and the A/B can be measured |
| Campus field trial with the web logger | real (to be recorded) | measured Indian numbers |

### 4.4 Why Bengaluru, and why Whitefield (measured)
`pipeline/city_select.py` cuts an identical 0.30° × 0.30° box (about 33 km) around 10 metros and counts
societies, office parks and malls with **two or more mapped gates on their boundary** (gate choice only matters there):

| City | delivery sites | ≥1 gate | **≥2 gates** | buildings with floor counts |
|---|---|---|---|---|
| **Bengaluru** | 3,677 | 2,862 | **2,140** | 13,658 |
| Delhi | 2,184 | 1,753 | 1,499 | 8,500 |
| Mumbai | 1,655 | 1,272 | 1,036 | 5,484 |
| Pune | 1,615 | 1,296 | 980 | 3,610 |
| Gurugram | 1,160 | 821 | 709 | 1,700 |
| Noida | 970 | 724 | 627 | 2,429 |
| Hyderabad | 737 | 575 | 448 | 1,753 |
| Chennai | 501 | 376 | 270 | 8,038 |
| Kolkata | 218 | 165 | 138 | 1,718 |
| Ahmedabad | 243 | 140 | 85 | 20,763 |

The study zone is the 3 km window (about one dark store's area) with the most such sites:
**S,W,N,E = 12.9631, 77.702, 12.9931, 77.732 (Whitefield–Brookefield–ITPL)**. It has 194 sites: 92 residential
societies (e.g. Prestige Shantiniketan, Brigade Metropolis, Sobha Lotus), 85 office parks (e.g. Brigade Tech
Gardens), 4 malls, 10 campuses and 3 hospitals. It also has 627 gates, 94 parking areas, 5,213 buildings, a road/path graph of 12,408 nodes,
and 218 named restaurants, cafés and fast-food outlets.

The first version counted all gated sites and picked central Bengaluru (Raj Bhavan, the Chief Minister's
residence, campuses). Those aren't realistic delivery destinations, so the ranking was restricted to societies, offices and malls.

The **IIIT-A campus** is in OSM (outline, roads, 3,489 buildings), but **no gates are mapped**, so the team surveys them with the logger.

### 4.5 GPS noise measured from the real traces (`data/eval/noise_calibration.json`)
| | |
|---|---|
| Stationary jitter | median 3.1 m, p95 17.9 m; RMS σ = 5.6 m per axis (the simulation uses this, so it's *noisier* than typical) |
| Error autocorrelation | ρ = 0.987 per second (errors drift slowly; they aren't independent) |
| Spikes (jumps > 25 m/s) | 0.07 % of fixes |
| Distance of moving fixes from mapped roads | median 2.0 m, p90 5.4 m |
| Sampling interval | median 15 s, used as the simulated ping rate (Eternal's real rate isn't public) |

### 4.6 Simulation assumptions (all in `pipeline/config.py::SimAssumptions`)
The map and the noise are real. These behaviours are **assumptions**, and every simulated number in the outputs is tagged "simulated":
- 90 days; 40–400 orders per building; realistic order-hour profile (lunch and dinner peaks).
- Share of trips by riders new to a building = **22 %** = the monthly new-partner share in the PDF's ref [1]. New riders pick the gate navigation would (shortest road + straight line to the pin). At a wrong gate the guard lets them in after 40–150 s with probability 0.35; otherwise they reroute.
- Each site has a true rider gate (OSM gates weighted ×2). 35 % of sites use a different gate at night; 10 % change gate permanently on day 60 (experienced riders keep using the old one for up to 14 days with probability 0.5).
- Handover mix: residential gate/lobby/doorstep 15/45/40 %; offices etc. 35/55/10 %.
- Floors from OSM `building:levels` where tagged, else 4–22 (residential) / 3–15 (office). Lift 1 m/s, wait 20–120 s, 3 m per floor; customer gets ready in 15–90 s; walking 1.2 m/s.
- **Today's behaviour: the customer starts coming down only after the rider calls on arrival** (call connects in 20–75 s). The A/B benefit depends heavily on this assumption.
- With DropSync: 15 % of customers ignore the notification (the rider then calls). 20 % of saved pins are wrong.
- Indoors (doorstep): 60 % of fixes are missing, the rest have 40–150 m accuracy.

---

## 5. Results (`data/eval/metrics.json`)

Profiles were learned on **days 0–59** (9,915 trips) and tested on **days 60–89** (5,119 trips), out of sample.
Ground truth is never visible to the profile builder.

### 5.1 Profile accuracy
| Metric | Result |
|---|---|
| Rider-gate hint precision (only when shown) | **94 %** (shown at 72 % of sites) |
| Baseline: new rider using navigation alone picks the right gate | 76 % |
| Rider gate, all sites / sites with ≥2 entries | 91 % / 81 % |
| Learning curve (multi-gate sites) | 95 % with 3 trips, **100 % from 10 trips** |
| Handover rule (all / where shown at checkout, 95 % of sites) | 92 % / **95 %** |
| Parking point error | median 4 m, p80 7 m |
| Handover-time estimate error | median 5 s |
| Night gate | 2 of 4 sites with ≥6 night trips found (8 % over all 24 sites: not enough night data); 0 false alarms |
| Gate changed on day 60 | right at 4 of 6 sites (14-day change detector) |
| Pin fixer (lobby sites, single order) | precision 56 %, recall 62 % |
| Robustness | gate accuracy 84–96 % for pings every 5–30 s; at 2×/3× measured noise the handover rule drops to 80 % / **36 %** |

### 5.2 Come-down sync A/B (4,048 lobby/gate orders replayed both ways)
| | Today | DropSync | DropSync after feedback* |
|---|---|---|---|
| Handover time (reach site → delivered), median | 6.8 min | **3.4 min** | 3.5 min |
| Rider wait at handover point, median / mean | 3.8 / 4.1 min | **0 / 1.0 min** | 0 / 1.1 min |
| Customer wait at handover point, median (p80) | — | 1.1 min (2.3) | **3 s** (1.1 min) |
| Orders needing a call | 100 % | **19 %** | 19 % |
| Rider-minutes saved per lobby/gate order | | **3.2** | 3.1 |

\* After feedback = the lead time re-learned from the observed "Coming" tap → customer arrival, once the sync is live (PDF §4.6).
85 % of notifications get a reply.

PDF §2.2 sizing re-run with 3.2 minutes: ₹168–252 crore/yr for Blinkit alone. **This inherits every assumption in 4.6.**
The campus trial is how to replace it with a measured number.

### 5.3 Live browser checks (same building, Skylark Esta)
DropSync on: rider waited **15 s**, handover 1.4 min. DropSync off (today): rider waited **7.4 min**, handover 8.5 min.

---

## 6. How it works (pipeline)

```
OSM India extract → osmium → zone extract → sites, gates, parking, buildings, floors, restaurants, road graph
OSM public traces → noise.py → measured GPS noise
simulate.py (real map + measured noise + stated assumptions) → trips + GPS pings + hidden truth
profile_builder.py → profiles  → evaluate.py (truth only here) → metrics
publish.py → data/out/*.json → db.py → PostGIS
backend (FastAPI) reads profiles → rider app / customer app / ops dashboard
```

Profile builder steps (PDF §3.1 and §4.1):
1. Clean pings: drop accuracy > 30 m and jumps > 25 m/s.
2. Stops: ≥ 60 s within a 25 m radius, with near-zero net speed over the window.
3. Entry gate: the **first sustained** outside→inside crossing of the site boundary (after a 3-fix majority filter that removes jitter flips). Each crossing votes for the nearest OSM access point (≤ 35 m). Crossings far from any mapped gate are DBSCAN-clustered into "learned gates" that OSM doesn't have. The winner is where **fast** trips (handover ≤ site median) entered.
4. Handover rule: no usable GPS fix for ≥ 45 s before "delivered" near a building → doorstep; final wait outside or at the edge of the site → gate; final wait inside the site → lobby.
5. Night gate (23:00–06:00) when it differs and has enough trips.
6. Gate-change detector: if the last 14 days (≥ 5 trips, ≥ 70 % agreement) point to a different gate, switch.
7. Parking: DBSCAN of the first stop at the site, snapped to OSM parking within 25 m.
8. Times: weighted median/p80 handover time; come-down lead = median wait at the handover point; tower floors adjust the lead (3 s per floor).
9. Recency weight 0.5^(age in days / 30).
10. Confidence: high = ≥ 40 trips and ≥ 75 % agreement; medium = ≥ 12 and ≥ 60 %. Riders see a gate hint only at medium or above **and** only if that gate is actually faster. Sync is used only for lobby/gate buildings at medium or above.

"Access points" (`pipeline/sitemodel.py`) are where mapped roads or paths cross a site boundary, merged within 30 m, marked as OSM gates if a gate node is within 20 m, and named by the nearest named road (245 of 289 have a road name, e.g. "Gate on Hoodi Main Road").

Real-time service (`backend/realtime.py`): on assignment it loads the profile and routes on the OSM road
graph. On every rider position it computes the ETA to the handover point (drive + guard check + parking +
walk). When ETA ≤ the building's lead time it sends **one** notification. Replies: Coming /
Leave with security / 2 more minutes. If there's no reply, the rider calls (fallback). On delivery it logs
the outcome and attaches fair-lateness evidence (within the building's usual p80, customer asked for time,
customer arrived after the rider).

---

## 7. The rider app (`/rider`), customer phone (`/track`), `/stage`

**What the team asked for:** show DropSync inside the app delivery partners actually use, looking like it.
Eternal's app can't be modified, so `/rider` is a **look-alike built from real reference screens**:
the official Play Store listings (Zomato Delivery Partner, Blinkit Delivery Partner) and public rider
tutorial videos that show the real New order, Feed and order-list screens. Every source and the
sampled colours are listed in **`ref/SOURCES.md`** (the images aren't stored here; they belong to their owners).
Copied: layout, structure, colours (accept bar #2CD86C, black Deny pill and card headers, #606060 "Pick up"
tag, #F4F4F4 pay box, grey Offline toggle), and the tab names Feed · Pocket · Gigs · Bazaar · Updates.
Not copied: no Zomato/Blinkit logo or wordmark; the font is Outfit (a free look-alike); it's labelled a concept.
Earnings are a flat ₹25 marked "demo" (PDF ref [12]: ₹20–30 per order), not invented pay.

Stages and what DropSync adds:
| Stage | Screen | DropSync inside it |
|---|---|---|
| Feed (home) | Offline/Online toggle, SOS, help, avatar (opens demo settings + language); "View details"; black-header **Today's progress** (Earnings (demo), Trips, Time on orders, Login time); tabs Feed · Pocket · Gigs · Bazaar · Updates | A DropSync card (in the style of the partner-tier card): "Building guides on — 151 buildings in your zone" |
| New order | Map with black round markers + dotted line, black **× Deny** pill, green-outlined **New order** tag, **Estimated earnings**, breakdown box, "Pickup: x kms \| Drop: y kms", grey **Pick up** tag, real OSM restaurant + its real street, "N mins away", green **Accept order** bar | Breakdown box shows **Building handover** time; drop row: DropSync badge + handover rule + gate by road name |
| Head to pickup | Route, Navigate, Call, "Reached pickup" bar (enabled on arrival) | — |
| At pickup | **Pickup 1 → Drop 1 timeline** with order number, "Order picked up" bar | — |
| To customer | ETA, Navigate, Call customer, "Reached drop location" slide | **Live customer strip** (will be told X min before / Coming / 2 more min / leave with security / at handover point) + **building guide** (gate by road name, parking, rule, usual handover, new-partner banner) |
| Handover | "Slide when handed over" | Customer status |
| Delivered | Summary | Fair-lateness check with reasons, "Did the building guide help?" |

- English and Hindi (one tap), including the fair-lateness reasons.
- Customer phone `/track`: follows the latest order automatically, with a step tracker, the checkout banner, **one** notification with three reply buttons, and "I'm at the lobby".
- `/stage`: both phones side by side, with a 5-step demo script.

---

## 8. Code map

```
dropsync/
├── README.md               overview + results (for judges)
├── WORKLOG.md              this file
├── requirements.txt        Python deps        docker-compose.yml   PostGIS
├── run_pipeline.sh         full pipeline in 9 steps
├── docker/osmium/          osmium-tool image (for machines without native osmium)
├── pipeline/
│   ├── config.py           paths, study zone, campus, ALL simulation assumptions
│   ├── geo.py              distances, UTM projection
│   ├── extract_cities.py   cut 10 city boxes + campus from the India file (one pass)
│   ├── city_select.py      measured city ranking + choose 3 km zone → data/study_area.json
│   ├── osm_extract.py      zone/campus → sites, gates, parking, buildings, restaurants, road graph
│   ├── traces.py           download OSM public GPS traces (tiled, 15 pages per tile)
│   ├── noise.py            measure GPS noise from them
│   ├── sitemodel.py        access points, towers + entrances, floors, road names (OSM only)
│   ├── simulate.py         simulated delivery history (parallel, deterministic per site)
│   ├── stops.py            ping cleaning + stop detection
│   ├── profile_builder.py  the profile builder (never reads truth_* columns)
│   ├── evaluate.py         out-of-sample evaluation, A/B, learning curve, robustness, sizing
│   ├── publish.py          final profiles → data/out
│   ├── db.py               PostGIS schema + loader
│   └── field.py            campus trial analysis
├── backend/
│   ├── app.py              FastAPI REST + WebSocket, serves web/dist
│   └── realtime.py         order sessions, routing, ETA, trigger, rider actions, fair lateness
├── web/src/
│   ├── rider/              RiderApp, BuildingGuide, Slide, RiderMap, Track, Stage, icons, i18n (EN/HI), rider.css
│   ├── pages/              Demo (three-panel), Ops, Trial
│   └── components/         OrderMap, RiderCard, CustomerScreen
├── tests/                  test_stops, test_pipeline_e2e, test_api (incl. rider flow), test_field
├── ref/SOURCES.md          where the rider-app design comes from (links, sampled colours, what was not copied)
└── data/
    ├── study_area.json     chosen zone
    ├── osm/city, osm/campus  extracted OSM layers + graph.graphml (+ restaurants.json)
    ├── sim/                trips.parquet, pings.parquet, truth_sites.json
    ├── eval/               metrics.json, noise_calibration.json, city_comparison.json, site_accuracy.csv, field_results.json
    ├── out/                profiles.json, sites.json, meta.json (+ live logs while the demo runs)
    └── field/              field-trial uploads (empty until the trial)
```
Not kept on the laptop (too large; can be re-downloaded): `data/raw/india-*.osm.pbf`, the raw traces CSV.

### API (FastAPI, http://localhost:8000)
| Endpoint | Purpose |
|---|---|
| `GET /api/health`, `/api/meta` | status, data sources, profile source (postgis/json) |
| `GET /api/sites`, `/api/sites/{id}/profile` | all sites; one site's geometry + profile |
| `POST /api/checkout` | checkout banner, building-adjusted ETA, pin fixer, lead time |
| `POST /api/orders` | create an order (`with_pickup`, `manual` for the rider app; `sync` on/off) |
| `GET /api/orders/latest`, `/api/orders/{id}` | order snapshot |
| `POST /api/orders/{id}/action` | rider actions: accept, reject, reached_pickup, picked_up, reached_drop, call, delivered |
| `POST /api/orders/{id}/reply` | customer reply: coming / security / later2 |
| `POST /api/orders/{id}/customer-here`, `/helped` | customer at handover point; rider feedback |
| `WS /ws/orders/{id}` | live order updates |
| `GET /api/metrics` | evaluation metrics, noise, city comparison, field and live summaries |
| `POST /api/trial/trips`, `/api/trial/gates`, `GET /api/trial/summary` | field-trial logger |

### Tests
`.venv/bin/python -m pytest -q`: **10 pass**. They cover stop detection and cleaning, the end-to-end builder on
the real zone (gate and rule ≥ 75 %, shown-hint precision ≥ 85 %), the checkout/pin fixer, the auto order flow
(exactly one nudge, sent before the rider reaches the handover point), the **rider-app flow** (offer → accept → restaurant →
picked up → nudge only after pickup → delivered, no call needed, illegal actions rejected), and the field-trial analysis.

---

## 9. All decisions and why

- **D1 — No LaDe / China data:** mentor instruction.
- **D2 — No public Indian delivery GPS dataset:** see 4.1.
- **D3 — OSM map = real layer; OSM traces = noise only:** see 4.2.
- **D4 — Data stack:** real map + measured noise + simulated history with known truth + real campus trial.
- **D5 — Local OSM file instead of Overpass:** the public Overpass servers returned 502/"at capacity" repeatedly. The Geofabrik India file + osmium is reproducible and works offline.
- **D6/D9 — City and zone chosen by measurement:** see 4.4. Campuses and hospitals were excluded from the ranking after the first pick landed on government residences.
- **D7 — Tech:** Python + pandas + scikit-learn (DBSCAN) + shapely + osmnx + pyosmium; PostGIS; FastAPI; React + Leaflet + Recharts. Push goes over **WebSocket** (Firebase needs a Firebase project; FCM remains the production path). React web instead of Flutter, so one codebase covers every screen.
- **D8 — Gaps in the PDF fixed in the build:**
  - "Handover time" mixes rider wait with customer descent, so the come-down lead is stored separately and refined from live replies.
  - Cold start: nothing is shown below medium confidence; OSM floors serve as the prior.
  - Rider ETA comes from OSM routing.
  - Recency decay and the night split are implemented.
  - PDF §4.4's LaDe study is replaced by the learning curve, robustness and recency tests.
  - Cosmetic: §4.5 lost its "→" arrows; references [13]/[14] are out of order.
- **D10 — Stop detection:** per-step speed checks broke stops under 3 m jitter (caught by a unit test); stops are now bounded by radius + net speed.
- **D11 — Accuracy fixes found by diagnosing errors trip by trip:**
  - Lobby vs gate decided by inside/outside the boundary. Before, lobbies next to the wall were misread as gates in 359 of 660 trips.
  - First *sustained* entry with a majority filter.
  - Per-trip gate voting instead of snapping cluster centres.
  - A site's candidate gates must lie in one connected road component.
  - The explicit 22 % new-to-building share replaced a rider pool that gave unrealistically few repeat visits.
  - Measured 15 s ping interval.
  - Gate-change detector, tower-level pin fixer, after-feedback A/B, night metric only on sites with enough data.
- **D12 — Rider app as a concept built on the public flow:** see section 7.
- **D13 — Restaurants:** pickups use 218 real named OSM food outlets in the zone.
- **D14 — Road-named gates:** the nearest named OSM road within 150 m along the network.
- **D15 — One call path:** "rider calls → customer starts coming down" is used both for today's flow and for the no-reply fallback.
- **D16 — Server stays on localhost:** exposing it on the college Wi-Fi is left to the team (section 2).

---

## 10. Problems hit and how they were solved (useful if you rerun anything)

| Problem | Fix |
|---|---|
| Rider app had no dark mode (it was pinned to light to match the reference) | Full dark theme with a **Theme: System / Light / Dark** choice in the avatar menu (saved per phone); dark map tiles and light route lines in dark mode |
| Changing the drop building in demo settings "did nothing": the selector was locked while an order was showing, and the Feed never said which building was selected | Selector always usable; changing it during an order request **replaces the request**; during an accepted order it says "applies to your next order"; Feed shows "Next order drops at: …" |
| Couldn't scroll: cards in the bottom sheet/Feed **shrank and got clipped** (flex children), so there was nothing to scroll | Cards no longer shrink (`flex: none`); sheets scroll with touch and mouse |
| Couldn't scroll Ops / Live demo with the mouse wheel: big maps swallowed the wheel | Page maps don't zoom on the wheel (use +/− or pinch) |
| The main action slider could scroll out of view on the drop leg | Action bar pinned to the bottom of the card, like the real app |
| Map fit happened before the card's height settled, hiding markers behind the card | Map refits when the card's height changes |
| UI audit (all pages × phone/tablet/laptop × light/dark): dark-mode slide and red buttons failed contrast (1.94:1 and 3.55:1) | Solid button tokens `--btn-go` #1f7a4d and `--btn-accent` #c62839 / #d03447 (≥ 4.9:1) |
| Maps glared bright white in dark mode | OSM tiles dimmed/inverted in dark mode (markers keep their colours) |
| Pin fixer told gate-building customers to move their home pin to the gate (and "Fix my pin" did nothing) | No pin suggestion for gate buildings; "Fix my pin" now moves the pin in the demo |
| Customer phone (`/track`) opened on an old "Delivered" order | Orders delivered more than 2 min ago count as finished → "No active order" |
| "1 entries (1 OSM gates)", raw ">=", cut-off field-trial hint, squeezed KPI labels on phones | Plurals, ≥, shorter hint, KPI tag wraps above the label |
| Overpass API overloaded (502, "all workers busy") | Use the Geofabrik India `.osm.pbf` + osmium locally |
| Geofabrik `india-latest` is a redirect → curl saved an HTML page | Use `curl -L`; check the MD5 of the dated file |
| OSM trackpoints API timed out (503) on the 3 km box | Tiled fetch (3×3 tiles, splitting further on timeout), 15 pages per tile |
| `pkill -f pattern` killed its own SSH/shell session | Use `pgrep`/`kill <pid>`, or a pattern that can't match the command itself |
| Python output buffered in `nohup` logs | Run with `python -u` |
| No routes between some gates (disconnected service lanes) | Restrict a site's candidate gates to one connected drive component |
| Simulation was slow (0.29 s/trip) | KD-tree for nearest nodes, per-site caches, timeline pointer, 12 parallel workers (now ~1 ms/trip) |
| Test orders polluted `data/out/sync_feedback.jsonl` | Tests write to a temp folder; the demo logs were cleared |
| react-leaflet 4 conflicts with React 19 | react-leaflet 5 |

---

## 11. Next steps for the team

1. **Campus field trial (IIIT-A)**, the one thing that turns simulated numbers into measured Indian numbers:
   - `cd web && npm run dev:https`, keep the API running on :8000, open `https://<laptop-ip>:5173/trial` on phones (accept the self-signed certificate).
   - Walk to each campus gate once and press **Mark gate here** with a name.
   - Record 40–60 mock deliveries, alternating **Control** (rider calls as today) and **DropSync sync**. Tap Arrived / Customer at handover / Delivered, tick "had to call", and the observer picks the gate actually used.
   - Run `.venv/bin/python -m pipeline.field` → the results appear on `/ops` (gate inference accuracy from GPS, rider wait control vs sync, call rate).
2. Optional: add the surveyed campus gates to OpenStreetMap (good pitch point).
3. Optional: if anyone gets real delivery-partner app screenshots, put them in `dropsync/ref/` and restyle `/rider` to match.
4. To rebuild everything from scratch: `./run_pipeline.sh data/raw/india-<date>.osm.pbf` (≈ 10 min on gpu80, excluding downloads).

---

## 12. The college server (gpu80, user kmpooja)

- SSH aliases on Aashay's laptop: `gpu170` (172.20.70.170) and `gpu80` (172.20.70.80), user `kmpooja`, key `~/.ssh/id_ed25519_er`.
- **gpu80 was used**: `/DATA` has 2.8 TB free. gpu170 was rejected because both its disks are about 100 % full and 20 users are logged in. gpu80's `/home` is also full, so nothing was written there.
- Work folder: **`/DATA/kmpooja/dropsync_eternal/`** (about 4.6 GB). Nothing outside it was touched.
  - `WORKLOG.md`: this file. **Copy it from here.**
  - `project/`: full copy of the code and data, including the India map file (`project/data/raw/india-261117.osm.pbf`) and the raw traces.
  - `env/`: isolated Python 3.12 + osmium-tool (micromamba), `bin/micromamba`, `mamba/`.
  - `env.sh`: `source` it before any command. It points HOME, caches and temp files into the folder and puts `env/bin` on PATH.
  - `README_FIRST.txt` explains the folder; `DropSync_Problem_Statement.pdf`.
- To rerun there:
  ```bash
  ssh gpu80
  source /DATA/kmpooja/dropsync_eternal/env.sh
  cd $W/project
  export DROPSYNC_WORKERS=12
  python -m pipeline.simulate && python -m pipeline.evaluate && python -m pipeline.publish
  ```
- **The folder is to be deleted when the project is finished** (Aashay's instruction). It hasn't been deleted yet, so the teammate can copy this file first. The project folder on the laptop keeps the authoritative copy.

---

## 13. Timeline

- **18 Nov 2026**
  - Read the PDF and analysed gaps.
  - Probed OSM traces and Overpass in Gurugram; searched for Indian datasets (none public).
  - Set up the Python venv, the PostGIS image and the React app; wrote the first pipeline modules.
  - Overpass was overloaded, so switched to the Geofabrik extract.
- **19 Nov 2026, morning**
  - Set up gpu80 (isolated environment inside the work folder).
  - Downloaded the India file there (MD5 OK) and cut 10 city extracts plus the campus in 77 s.
  - Ran the city comparison and chose Bengaluru/Whitefield; extracted the OSM layers.
  - Wrote the backend, evaluation, field-trial module and web app.
- **19 Nov, midday**
  - Downloaded the real traces (tiled) and measured the noise.
  - Fixed accuracy issues found by trip-level diagnostics (D10, D11).
  - Ran the full simulation and evaluation on gpu80 and copied the data back.
  - Loaded PostGIS and verified the UI in headless Firefox.
  - Wrote the README results.
- **19 Nov, late night**
  - Rider app: dark mode + theme setting, building change that takes effect (and replaces a pending request), scroll fixes (non-shrinking cards, page maps don't capture the wheel), pinned action bar, map refit on card resize, theme-aware route lines.
  - Verified with touch-scroll tests on an emulated phone (Chromium) and full flows in light/dark/Hindi; 10 tests pass.
- **19 Nov, night**
  - Found real rider-app reference screens (Play Store listings + public tutorial videos; see `ref/SOURCES.md`) and rebuilt `/rider` to match their layout and sampled colours (Feed, New order, pickup timeline, green action bar with black knob, Deny pill), plus real street names for pickups.
  - Fixed the invisible "Pick up" tag text, Hindi letter-spacing, a theme-colour collision on the customer strip, and "1 mins".
  - Verified the full flow in light, dark-system and Hindi; 10 tests pass.
- **19 Nov, evening**
  - UI audit with screenshots of every page in 3 sizes × 2 themes, plus the full rider flow in dark mode. Fixed the issues listed in section 10.
  - 10 tests pass; no page errors, overflow or clipped text at any size.
- **19 Nov, afternoon**
  - Built the rider app (`/rider`), customer phone (`/track`) and `/stage`.
  - Added real restaurants for pickups, road-named gates, the live customer strip, Hindi, and translated fair-lateness reasons.
  - Verified the full flow in the browser; 10 tests pass.
  - Rewrote this log in full.
