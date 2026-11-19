"""Passcode gate (only active when DROPSYNC_PASSCODE is set). Runs in a subprocess so
the env var does not leak into the other tests."""
import os
import subprocess
import sys

CODE = r'''
from fastapi.testclient import TestClient
from backend.app import app
c = TestClient(app)
assert c.get("/rider").status_code == 401                       # page -> passcode screen
assert "Passcode" in c.get("/rider").text
assert c.get("/api/sites").status_code == 401                   # API refused
assert c.get("/api/health").status_code == 200                  # health stays open (host checks)
bad = c.post("/login", data={"code": "nope", "next": "/rider"}, follow_redirects=False)
assert bad.status_code == 401 and "Wrong passcode" in bad.text
ok = c.post("/login", data={"code": "eternal123", "next": "/rider"}, follow_redirects=False)
assert ok.status_code == 303 and ok.headers["location"] == "/rider"
assert c.get("/api/sites").status_code == 200                   # cookie set -> allowed
evil = TestClient(app).post("/login", data={"code": "eternal123", "next": "//evil.example"}, follow_redirects=False)
assert evil.headers["location"] == "/"                          # no open redirect
print("passcode ok")
'''


def test_passcode_gate():
    env = dict(os.environ, DROPSYNC_PASSCODE="eternal123", DROPSYNC_HTTPS="0")
    r = subprocess.run([sys.executable, "-c", CODE], cwd=os.path.dirname(os.path.dirname(__file__)),
                       env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "passcode ok" in r.stdout
