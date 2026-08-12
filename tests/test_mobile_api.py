import os

os.environ.setdefault("EMPTY_CHAIR_DB", "test_empty_chair.db")
os.environ.setdefault("EMPTY_CHAIR_DEMO_MODE", "true")
os.environ.setdefault("EMPTY_CHAIR_SESSION_SECRET", "mobile-api-test-secret")

from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_mobile_api_requires_authentication():
    for path in (
        "/api/me",
        "/api/dashboard",
        "/api/openings",
        "/api/recovery",
        "/api/customers",
        "/api/artists",
        "/api/bookings",
    ):
        response = client.get(path)
        assert response.status_code == 401, (path, response.text)


def test_mobile_login_rejects_bad_credentials():
    response = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_mobile_login_validates_required_fields():
    response = client.post("/api/auth/login", json={"email": "", "password": ""})
    assert response.status_code == 400
