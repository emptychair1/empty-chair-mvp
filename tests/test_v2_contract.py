import os
import pathlib

os.environ.setdefault("EMPTY_CHAIR_DB", "/tmp/empty-chair-v2-test.db")
os.environ.setdefault("EMPTY_CHAIR_WORKER_ENABLED", "false")
os.environ.setdefault("EMPTY_CHAIR_SESSION_SECRET", "test-secret")
os.environ.setdefault("EMPTY_CHAIR_BASE_URL", "http://testserver")

from fastapi.testclient import TestClient
import v2_app


def setup_function():
    p = pathlib.Path("/tmp/empty-chair-v2-test.db")
    if p.exists():
        p.unlink()
    v2_app.init_db()


def test_health_and_version():
    client = TestClient(v2_app.app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["version"] == "2.0.0"


def test_headless_landing_is_amber_and_has_no_dashboard():
    client = TestClient(v2_app.app)
    text = client.get("/").text
    assert "#0B0905" in text
    assert "#FFB000" in text
    assert "DON'T LEAVE IT EMPTY." in text
    assert "dashboard" not in text.lower()
    assert "m4" not in text.lower()
    assert "demand engine" not in text.lower()


def test_manifest_is_pwa_and_square_icon():
    client = TestClient(v2_app.app)
    manifest = client.get("/manifest.webmanifest").json()
    assert manifest["display"] == "standalone"
    assert manifest["icons"][0]["src"] == "/icon.svg"
    svg = client.get("/icon.svg").text
    assert 'viewBox="0 0 1024 1024"' in svg
    assert v2_app.AMBER in svg
    assert v2_app.BG in svg


def test_bootstrap_is_v2_only():
    text = pathlib.Path("bootstrap.py").read_text()
    assert "from v2_app import app" in text
    for token in ["m4_", "contest", "concierge", "demand_", "meeting_", "pilot_", "stripe_"]:
        assert token not in text


def test_production_entry_is_v2_only():
    text = pathlib.Path("production_entry.py").read_text()
    assert "from bootstrap import app" in text
    assert "crybaby" not in text
    assert "contest" not in text
    assert "demand_" not in text


def test_recovery_ranking_prefers_short_notice_and_history():
    opening = {"title": "American Traditional", "value_cents": 45000}
    strong = {"completed_count": 5, "no_show_count": 0, "short_notice": 1, "styles": "traditional", "budget_cents": 50000}
    weak = {"completed_count": 0, "no_show_count": 2, "short_notice": 0, "styles": "", "budget_cents": 0}
    assert v2_app.score_client(strong, opening) > v2_app.score_client(weak, opening)
