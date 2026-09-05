from pathlib import Path


def test_v2_bootstrap_is_minimal():
    text = Path("bootstrap.py").read_text()
    assert "from v2_app import app" in text
    assert "import v2_auth" in text
    assert "import v2_pwa" in text
    forbidden = ["m4_", "concierge", "contest", "demand_", "meeting_v2", "admin_dashboard"]
    assert not any(name in text for name in forbidden)


def test_v2_auth_contract_present():
    text = Path("v2_auth.py").read_text()
    assert "CONTINUE WITH APPLE" in text
    assert "CONTINUE WITH GOOGLE" in text
    assert "/auth/apple/callback" in text
    assert "/auth/google/login/callback" in text
    assert "openid email profile" in text
    assert "PyJWKClient" in text


def test_runtime_dependencies_are_only_required_v2_dependencies():
    req = Path("requirements.txt").read_text().lower()
    for package in ["fastapi", "uvicorn", "python-multipart", "psycopg2-binary", "pyjwt"]:
        assert package in req
    for old in ["twilio", "resend", "jinja2", "stripe"]:
        assert old not in req


def test_product_is_headless():
    text = Path("v2_app.py").read_text()
    assert "ARMED." in text
    assert "YOU CAN CLOSE THIS NOW." in text
    assert "TAKE THE CHAIR" in text
    assert "CHECK CALENDAR" in text
    assert "EMPTY CHAIR // FILLED" in text


def test_google_and_apple_calendar_paths_still_exist():
    text = Path("v2_app.py").read_text()
    assert "GOOGLE CALENDAR" in text
    assert "APPLE CALENDAR" in text
    assert "apple_discover_calendars" in text
    assert "google_events" in text
