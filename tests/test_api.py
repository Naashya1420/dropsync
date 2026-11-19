"""API tests against the published profiles (skipped until the pipeline has run)."""
import asyncio
import json

import pytest

from pipeline.config import OUT_DIR

pytestmark = pytest.mark.skipif(not (OUT_DIR / "profiles.json").exists(), reason="profiles not published")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from fastapi.testclient import TestClient
    from backend.app import app, hub
    hub().feedback_path = tmp_path_factory.mktemp("fb") / "sync_feedback.jsonl"  # keep test orders out of data/out
    return TestClient(app)


def _sync_site(client):
    sites = client.get("/api/sites").json()
    s = next(x for x in sites if x["show_sync"] and x["show_gate_hint"])
    return s


def test_health_and_sites(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["profiles"] > 0
    sites = client.get("/api/sites").json()
    assert any(s["show_sync"] for s in sites)


def test_checkout_banner_and_pin_fix(client):
    sites = client.get("/api/sites").json()
    s = next(x for x in sites if x["show_sync"] and x["handover_type"] == "lobby")
    d = client.get(f"/api/sites/{s['site_id']}/profile").json()
    t = d["site"]["towers"][0]
    r = client.post("/api/checkout", json=dict(site_id=s["site_id"], tower_id=t["tower_id"],
                                                pin_lat=t["lat"], pin_lon=t["lon"])).json()
    assert r["banner"] and r["handover_type"] == "lobby"
    assert r["pin_fix"] is None                      # pin on the tower: nothing to fix
    assert r["eta_min"] >= 10
    # a pin 300 m away must trigger the pin fixer
    r2 = client.post("/api/checkout", json=dict(site_id=s["site_id"], tower_id=t["tower_id"],
                                                 pin_lat=t["lat"] + 0.0027, pin_lon=t["lon"])).json()
    assert r2["pin_fix"] is not None
    # gate-handover buildings never ask the customer to move their home pin
    g = next(x for x in sites if x["show_sync"] and x["handover_type"] == "gate")
    gd = client.get(f"/api/sites/{g['site_id']}/profile").json()["site"]["towers"][0]
    r3 = client.post("/api/checkout", json=dict(site_id=g["site_id"], pin_lat=gd["lat"] + 0.0027, pin_lon=gd["lon"])).json()
    assert r3["pin_fix"] is None


def test_order_flow_notifies_once_and_delivers(client):
    from backend.app import hub
    s = _sync_site(client)
    o = client.post("/api/orders", json=dict(site_id=s["site_id"], speedup=60, start_dist_m=600)).json()
    h = hub()
    order = h.orders[o["order_id"]]

    async def drive():
        task = asyncio.create_task(h.run(order, tick_s=0.01))
        for _ in range(4000):
            await asyncio.sleep(0.01)
            if order.notified_at is not None and order.reply is None:
                h.reply(order, "coming")
            if order.delivered_at is not None:
                break
        await task
    asyncio.run(drive())
    kinds = [e["kind"] for e in order.events]
    assert kinds.count("notify") == 1
    assert "delivered" in kinds
    # the nudge must arrive before the rider reaches the handover point
    assert order.notified_at <= order.rider_at_hp_at
    assert order.fair is not None
    json.dumps(h.snapshot(order), default=float)


def test_rider_app_manual_flow(client):
    """Rider-app mode: real restaurant pickup, stages advance only on the rider's taps."""
    from backend.app import hub
    s = _sync_site(client)
    o = client.post("/api/orders", json=dict(site_id=s["site_id"], speedup=60, with_pickup=True, manual=True)).json()
    assert o["pickup"] and o["pickup"]["name"] and o["phase"] in ("assigned", "offered")
    oid = o["order_id"]
    assert client.get("/api/orders/latest").json()["order_id"] == oid
    h = hub()
    order = h.orders[oid]

    async def drive():
        task = asyncio.create_task(h.run(order, tick_s=0.01))
        await asyncio.sleep(0.05)
        assert h.action(order, "picked_up") is not None          # not allowed before accepting
        assert h.action(order, "accept") is None
        for _ in range(6000):
            await asyncio.sleep(0.01)
            if order.phase == "at_pickup":
                assert h.action(order, "reached_pickup") is None
            elif order.phase == "pickup_wait":
                assert h.action(order, "picked_up") is None
            if order.notified_at is not None and order.reply is None:
                h.reply(order, "coming")
            if order.phase in ("parking", "walk") and order.arrived_at is None:
                h.action(order, "reached_drop")
            if order.phase in ("at_handover", "indoors") and (order.customer_at_hp_at or order.phase == "indoors"):
                assert h.action(order, "delivered") is None
                break
        await task
    asyncio.run(drive())
    kinds = [e["kind"] for e in order.events]
    for k in ("offered", "accepted", "reached_pickup", "picked_up", "notify", "arrived", "delivered"):
        assert k in kinds, (k, kinds)
    assert kinds.count("notify") == 1
    assert order.notified_at > order.picked_up_at       # nudge only after pickup, during the drop leg
    assert order.calls == 0                              # nobody needed to call
