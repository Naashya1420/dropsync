"""DropSync real-time service (FastAPI).

Run:  uvicorn backend.app:app --port 8000
Data: data/out/{profiles,sites,meta}.json, data/eval/*.json, data/osm/city/graph.graphml
      Profiles are read from PostGIS when DATABASE_URL is set and reachable,
      otherwise from data/out/profiles.json (so the demo never depends on Docker).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .realtime import Hub, Router, hav, lead_time

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "out"
EVAL = DATA / "eval"
FIELD = DATA / "field"
IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="DropSync", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------------------------------------------------------------- optional passcode
# Set DROPSYNC_PASSCODE on the host to keep a public deployment private: visitors see a
# passcode page first; API and WebSocket calls without the cookie are refused.
PASSCODE = os.environ.get("DROPSYNC_PASSCODE", "").strip()
_TOKEN = hashlib.sha256(f"dropsync:{PASSCODE}".encode()).hexdigest() if PASSCODE else ""
_OPEN = ("/login", "/favicon.svg", "/api/health", "/icons/", "/app.webmanifest", "/rider.webmanifest",
         "/track.webmanifest")

# Installable web app (Add to Home Screen opens full-screen, not in Safari): each phone
# page gets its own manifest, icon and name so the icon opens the right screen.
_APPS = {"rider": ("rider", "DropSync Rider", "/icons/rider-180.png"),
         "track": ("track", "DropSync Customer", "/icons/customer-180.png")}


def _app_for(path: str):
    key = path.strip("/").split("/")[0]
    return _APPS.get(key, ("app", "DropSync", "/icons/app-180.png"))


def _webapp_head(path: str) -> str:
    man, title, icon = _app_for(path)
    return (f'<link rel="manifest" href="/{man}.webmanifest"><link rel="apple-touch-icon" href="{icon}">'
            '<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">'
            f'<meta name="apple-mobile-web-app-title" content="{html.escape(title)}">')
_LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>DropSync</title>__HEAD__
<style>:root{color-scheme:light dark}body{margin:0;min-height:100dvh;display:grid;place-items:center;
font-family:system-ui,sans-serif;background:#f6f5f3;color:#1d1f23}
@media (prefers-color-scheme:dark){body{background:#131416;color:#eceef0}input{background:#1c1e21;color:#eceef0}}
form{display:flex;flex-direction:column;gap:12px;width:min(320px,90vw)}
input{font:inherit;padding:14px;border-radius:12px;border:1px solid #8888;font-size:18px}
button{font:inherit;padding:14px;border-radius:12px;border:0;background:#c62839;color:#fff;font-weight:700;font-size:16px}
p{margin:0;color:#c62839;min-height:1.2em}</style></head><body>
<form method="post" action="/login"><b style="font-size:22px">DropSync</b>
<input name="code" type="password" inputmode="text" autocomplete="current-password" placeholder="Passcode" autofocus aria-label="Passcode">
<input name="next" type="hidden" value="__NEXT__"><button>Open</button><p>__ERR__</p></form></body></html>"""


def _authed(cookies) -> bool:
    return not PASSCODE or hmac.compare_digest(cookies.get("ds_pass", ""), _TOKEN)


@app.middleware("http")
async def passcode_gate(request: Request, call_next):
    path = request.url.path
    if not PASSCODE or path.startswith(_OPEN) or _authed(request.cookies):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "passcode required"}, status_code=401)
    nxt = path if path.startswith("/") and not path.startswith("//") else "/"
    page = _LOGIN_HTML.replace("__NEXT__", html.escape(nxt)).replace("__ERR__", "").replace("__HEAD__", _webapp_head(nxt))
    return HTMLResponse(page, status_code=401)


@app.post("/login")
async def login(code: str = Form(""), next: str = Form("/")):
    if PASSCODE and hmac.compare_digest(code.strip(), PASSCODE):
        dest = next if next.startswith("/") and not next.startswith("//") else "/"
        r = RedirectResponse(dest, status_code=303)
        r.set_cookie("ds_pass", _TOKEN, max_age=30 * 24 * 3600, httponly=True, samesite="lax",
                     secure=os.environ.get("DROPSYNC_HTTPS", "1") == "1")
        return r
    page = (_LOGIN_HTML.replace("__NEXT__", html.escape(next)).replace("__ERR__", "Wrong passcode")
            .replace("__HEAD__", _webapp_head(next)))
    return HTMLResponse(page, status_code=401)


def _load_json(p: Path, default=None):
    return json.loads(p.read_text()) if p.exists() else default


SITES: dict = _load_json(OUT / "sites.json", {})
META: dict = _load_json(OUT / "meta.json", {})
PROFILES: dict = {}
PROFILE_SOURCE = "json"


def _load_profiles():
    global PROFILES, PROFILE_SOURCE
    url = os.environ.get("DATABASE_URL")
    if url:
        try:
            from pipeline.db import fetch_profiles
            PROFILES = fetch_profiles(url)
            PROFILE_SOURCE = "postgis"
            return
        except Exception as e:  # DB down -> JSON fallback
            print(f"[api] PostGIS unavailable ({e!r}); using profiles.json")
    PROFILES = _load_json(OUT / "profiles.json", {})
    PROFILE_SOURCE = "json"


_load_profiles()
_router: Router | None = None
_hub: Hub | None = None


def hub() -> Hub:
    global _router, _hub
    if _hub is None:
        _router = Router(DATA / "osm" / "city" / "graph.graphml")
        FIELD.mkdir(parents=True, exist_ok=True)
        _hub = Hub(_router, SITES, lambda sid: PROFILES.get(sid), OUT / "sync_feedback.jsonl",
                   restaurants=_load_json(DATA / "osm" / "city" / "restaurants.json", []))
    return _hub


def _centroid(poly):
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


# --------------------------------------------------------------------- read API
@app.get("/api/health")
def health():
    return dict(ok=True, profiles=len(PROFILES), sites=len(SITES), profile_source=PROFILE_SOURCE)


@app.get("/api/meta")
def meta():
    return dict(META, profile_source=PROFILE_SOURCE)


@app.get("/api/sites")
def sites():
    out = []
    for sid, s in SITES.items():
        p = PROFILES.get(sid) or {}
        lat, lon = _centroid(s["polygon"])
        out.append(dict(
            site_id=sid, name=s["name"], kind=s["kind"], lat=lat, lon=lon, polygon=s["polygon"],
            trips=p.get("trips", 0), confidence=p.get("confidence", "none"),
            handover_type=(p.get("handover") or {}).get("type"),
            show_gate_hint=p.get("show_gate_hint", False), show_sync=p.get("show_sync", False),
            gate=p.get("gate_day"), gate_night=p.get("gate_night"), parking=p.get("parking"),
            handover_median_s=(p.get("handover_time_s") or {}).get("median"),
            n_access_points=len(s["access_points"]), n_osm_gates=sum(a["osm_gate"] for a in s["access_points"]),
            towers=len(s["towers"]), cold_start=not bool(p)))
    return out


@app.get("/api/sites/{site_id:path}/profile")
def site_profile(site_id: str):
    if site_id not in SITES:
        raise HTTPException(404, "unknown site")
    return dict(site=SITES[site_id], profile=PROFILES.get(site_id))


@app.get("/api/metrics")
def metrics():
    return dict(
        metrics=_load_json(EVAL / "metrics.json"),
        noise=_load_json(EVAL / "noise_calibration.json"),
        cities=_load_json(EVAL / "city_comparison.json"),
        field=_field_summary(),
        live=_live_summary(),
    )


def _live_summary():
    p = OUT / "sync_feedback.jsonl"
    if not p.exists():
        return dict(orders=0)
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    synced = [r for r in rows if r.get("sync")]
    return dict(orders=len(rows), synced=len(synced),
                coming_rate=round(sum(r.get("reply") == "coming" for r in synced) / len(synced), 3) if synced else None,
                median_rider_wait_s=sorted(r["rider_wait_s"] for r in rows)[len(rows) // 2] if rows else None)


# ------------------------------------------------------------------ checkout API
class CheckoutReq(BaseModel):
    site_id: str
    tower_id: str | None = None
    pin_lat: float | None = None
    pin_lon: float | None = None
    base_eta_min: float = 10.0


@app.post("/api/checkout")
def checkout(req: CheckoutReq):
    """Expectation banner + per-building ETA correction + pin fixer (PDF 3.3)."""
    s = SITES.get(req.site_id)
    if not s:
        raise HTTPException(404, "unknown site")
    p = PROFILES.get(req.site_id) or {}
    tower = next((t for t in s["towers"] if t["tower_id"] == req.tower_id), s["towers"][0])
    banner = None
    h = p.get("handover") or {}
    if p.get("show_checkout_banner"):
        banner = {"lobby": "Delivery at the lobby for your building. Your rider can't come up; we'll tell you when to come down.",
                  "gate": "Delivery at the gate for your building. We'll tell you when to come down.",
                  "doorstep": "Doorstep delivery available for your building."}[h["type"]]
    ho = (p.get("handover_time_s") or {}).get("median")
    eta = req.base_eta_min + (ho / 60 if ho else 0)
    pin_fix = None
    if req.pin_lat is not None and h.get("type") in ("lobby", "doorstep") and p.get("show_checkout_banner"):
        near = min(s["towers"], key=lambda t: hav((t["lat"], t["lon"]), (req.pin_lat, req.pin_lon)))
        d = hav((near["lat"], near["lon"]), (req.pin_lat, req.pin_lon))
        if d > 25:
            pin_fix = dict(reason=f"Your pin is {d:.0f} m from the nearest tower; riders hand over at tower lobbies here.",
                           suggest=dict(lat=near["lat"], lon=near["lon"], tower_id=near["tower_id"]))
    # Gate-handover buildings: no pin suggestion. The handover point is the gate, not the
    # customer's home, and the banner already tells them where to come.
    lead, why = lead_time(p, tower)
    return dict(banner=banner, handover_type=h.get("type"), confidence=p.get("confidence", "none"),
                eta_min=round(eta, 1), eta_building_add_min=round(ho / 60, 1) if ho else 0,
                pin_fix=pin_fix, lead_s=lead, lead_explain=why)


# -------------------------------------------------------------------- orders API
class OrderReq(BaseModel):
    site_id: str
    tower_id: str | None = None
    pin_lat: float | None = None
    pin_lon: float | None = None
    new_partner: bool = True
    speedup: float = Field(8.0, ge=1, le=60)
    start_dist_m: float = Field(1200, ge=200, le=4000)
    sync: bool = True
    hour: int | None = None
    with_pickup: bool = False   # rider app: real OSM restaurant pickup leg first
    manual: bool = False        # rider app: stages advance on the rider's taps


@app.post("/api/orders")
async def create_order(req: OrderReq):
    if req.site_id not in SITES:
        raise HTTPException(404, "unknown site")
    hr = req.hour if req.hour is not None else datetime.now(IST).hour
    pin = (req.pin_lat, req.pin_lon) if req.pin_lat is not None else None
    o = hub().create(req.site_id, req.tower_id, pin, req.new_partner, req.speedup, req.start_dist_m, hr, req.sync,
                     with_pickup=req.with_pickup, manual=req.manual)
    asyncio.create_task(hub().run(o))
    return hub().snapshot(o)


@app.get("/api/orders/latest")
def latest_order():
    """Most recent order: lets the customer's phone open tracking without an order id."""
    h = hub()
    if not h.latest or h.latest not in h.orders:
        raise HTTPException(404, "no orders yet")
    return h.snapshot(h.orders[h.latest])


class Action(BaseModel):
    action: str


@app.post("/api/orders/{order_id}/action")
async def order_action(order_id: str, a: Action):
    o = hub().orders.get(order_id)
    if not o:
        raise HTTPException(404)
    err = hub().action(o, a.action)
    if err:
        raise HTTPException(409, err)
    await hub().broadcast(o)
    return hub().snapshot(o)


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    o = hub().orders.get(order_id)
    if not o:
        raise HTTPException(404)
    return hub().snapshot(o)


class Reply(BaseModel):
    choice: str = Field(pattern="^(coming|security|later2)$")


@app.post("/api/orders/{order_id}/reply")
async def reply(order_id: str, r: Reply):
    o = hub().orders.get(order_id)
    if not o:
        raise HTTPException(404)
    hub().reply(o, r.choice)
    await hub().broadcast(o)
    return dict(ok=True)


@app.post("/api/orders/{order_id}/customer-here")
async def customer_here(order_id: str):
    o = hub().orders.get(order_id)
    if not o:
        raise HTTPException(404)
    hub().customer_at_handover(o)
    await hub().broadcast(o)
    return dict(ok=True)


class Helped(BaseModel):
    helped: bool


@app.post("/api/orders/{order_id}/helped")
def helped(order_id: str, h: Helped):
    o = hub().orders.get(order_id)
    if o:
        o.helped = h.helped
    with open(OUT / "hint_feedback.jsonl", "a") as f:
        f.write(json.dumps(dict(order_id=order_id, helped=h.helped, ts=time.time())) + "\n")
    return dict(ok=True)


@app.websocket("/ws/orders/{order_id}")
async def ws_order(ws: WebSocket, order_id: str):
    if not _authed(ws.cookies):
        await ws.close(code=4401)
        return
    await ws.accept()
    o = hub().orders.get(order_id)
    if not o:
        await ws.close(code=4404)
        return
    o.subscribers.add(ws)
    await ws.send_text(json.dumps(hub().snapshot(o), default=float))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        o.subscribers.discard(ws)


# ----------------------------------------------------------- field-trial logger
class TrialPoint(BaseModel):
    ts: float
    lat: float
    lon: float
    accuracy_m: float | None = None


class TrialTrip(BaseModel):
    trip_id: str
    role: str = "rider"
    variant: str = Field("control", pattern="^(control|sync)$")
    destination: str
    actual_gate: str | None = None
    handover_type: str | None = None
    arrived_ts: float | None = None
    customer_ready_ts: float | None = None
    delivered_ts: float | None = None
    called: bool = False
    points: list[TrialPoint]


class TrialGate(BaseModel):
    name: str
    lat: float
    lon: float
    accuracy_m: float | None = None
    rider_allowed: bool = True


@app.post("/api/trial/trips")
def trial_trip(t: TrialTrip):
    FIELD.mkdir(parents=True, exist_ok=True)
    (FIELD / f"trip_{t.trip_id}.json").write_text(t.model_dump_json())
    return dict(ok=True, points=len(t.points))


@app.post("/api/trial/gates")
def trial_gate(g: TrialGate):
    FIELD.mkdir(parents=True, exist_ok=True)
    p = FIELD / "gates.json"
    gates = _load_json(p, [])
    gates.append(dict(g.model_dump(), ts=time.time()))
    p.write_text(json.dumps(gates, indent=1))
    return dict(ok=True, gates=len(gates))


@app.get("/api/trial/summary")
def trial_summary():
    return _field_summary()


def _field_summary():
    if not FIELD.exists():
        return dict(trips=0, gates=0)
    trips = [json.loads(p.read_text()) for p in FIELD.glob("trip_*.json")]
    gates = _load_json(FIELD / "gates.json", [])
    res = _load_json(EVAL / "field_results.json")
    return dict(trips=len(trips), gates=len(gates), gate_list=gates,
                by_variant={v: sum(t["variant"] == v for t in trips) for v in ("control", "sync")},
                results=res)


# --------------------------------------------------------------- static web app
WEB = ROOT / "web" / "dist"
if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    _INDEX = (WEB / "index.html").read_text()

    @app.get("/{path:path}")
    def spa(path: str):
        f = WEB / path
        if path and f.is_file() and f.resolve().is_relative_to(WEB.resolve()):
            if f.suffix == ".webmanifest":
                return FileResponse(f, media_type="application/manifest+json")
            return FileResponse(f)
        man, title, icon = _app_for("/" + path)
        page = (_INDEX.replace("/app.webmanifest", f"/{man}.webmanifest")
                .replace("/icons/app-180.png", icon)
                .replace('content="DropSync" />', f'content="{html.escape(title)}" />')
                .replace("<title>DropSync</title>", f"<title>{html.escape(title)}</title>"))
        return HTMLResponse(page)
