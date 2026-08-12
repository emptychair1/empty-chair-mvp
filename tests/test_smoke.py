import os
from pathlib import Path

TEST_DB = Path("test_empty_chair.db")

os.environ["EMPTY_CHAIR_DB"] = str(TEST_DB)
os.environ["EMPTY_CHAIR_DEMO_MODE"] = "true"
os.environ["EMPTY_CHAIR_SESSION_SECRET"] = "test-secret"
os.environ.pop("DATABASE_URL", None)

from fastapi.testclient import TestClient
from app import app
import app as core


def setup_module():
    if TEST_DB.exists():
        TEST_DB.unlink()
    core.init_db()


def teardown_module():
    if TEST_DB.exists():
        TEST_DB.unlink()


def create_test_account(client):
    response = client.post(
        "/signup",
        data={
            "name": "Test Owner",
            "shop_name": "Test Tattoo Studio",
            "email": "owner@example.com",
            "password": "testing123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    return response


def test_health_check():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "sqlite"


def test_public_auth_pages_render():
    with TestClient(app) as client:
        for path in ["/login", "/signup", "/forgot-password"]:
            response = client.get(path)
            assert response.status_code == 200, path


def test_private_pages_redirect_when_logged_out():
    with TestClient(app) as client:
        for path in ["/", "/artists", "/bookings", "/recovery", "/customers", "/settings"]:
            response = client.get(path, follow_redirects=False)
            assert response.status_code in (302, 303), path
            assert response.headers["location"].startswith("/login")


def test_owner_pages_render_after_signup():
    with TestClient(app) as client:
        create_test_account(client)
        for path in ["/", "/artists", "/bookings", "/recovery", "/customers", "/settings"]:
            response = client.get(path)
            assert response.status_code == 200, f"{path}: {response.text[:300]}"


def test_basic_opening_flow():
    with TestClient(app) as client:
        create_test_account(client)

        response = client.post(
            "/artists",
            data={
                "name": "Alex Test",
                "email": "",
                "phone": "",
                "styles": "traditional",
                "services": "tattoo",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        conn = core.connect()
        artist = core.db_fetchone(conn, "SELECT * FROM artists WHERE name = ?", ("Alex Test",))
        conn.close()
        assert artist

        response = client.post(
            "/openings",
            data={
                "artist_id": artist["id"],
                "date": "2026-08-15",
                "start_time": "14:00",
                "service": "tattoo",
                "style": "traditional",
                "price": "450",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Alex Test" in response.text
