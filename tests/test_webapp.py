"""Add to Home Screen: each phone page must be an installable, full-screen web app."""
import json

import pytest

from pipeline.config import ROOT

pytestmark = pytest.mark.skipif(not (ROOT / "web" / "dist" / "index.html").exists(), reason="web app not built")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from backend.app import app
    return TestClient(app)


@pytest.mark.parametrize("path,manifest,icon,title", [
    ("/rider", "/rider.webmanifest", "/icons/rider-180.png", "DropSync Rider"),
    ("/track", "/track.webmanifest", "/icons/customer-180.png", "DropSync Customer"),
    ("/stage", "/app.webmanifest", "/icons/app-180.png", "DropSync"),
])
def test_page_is_installable(client, path, manifest, icon, title):
    h = client.get(path).text
    assert f'rel="manifest" href="{manifest}"' in h
    assert f'rel="apple-touch-icon" href="{icon}"' in h
    assert 'name="apple-mobile-web-app-capable" content="yes"' in h
    assert f"<title>{title}</title>" in h
    m = client.get(manifest)
    assert m.headers["content-type"].startswith("application/manifest+json")
    data = json.loads(m.text)
    assert data["display"] == "standalone" and data["start_url"] == path.replace("/stage", "/stage")
    assert client.get(icon).headers["content-type"] == "image/png"
