from pathlib import Path


def test_v2_bootstrap_is_minimal():
    text = Path("bootstrap.py").read_text()
    assert "from v2_app import app" in text
    assert "import v2_db_namespace" in text
    assert "import v2_sms_only" in text
    assert "import v2_offer_delivery" in text
    assert "import v2_auth" in text
    assert "import v2_pwa" in text
    assert "import v2_native_calendar" in text
    assert "import v2_native_auth" in text
    assert "import v2_native_finalize_bridge" in text
    forbidden = ["m4_", "concierge", "contest", "demand_", "meeting_v2", "admin_dashboard"]
    assert not any(name in text for name in forbidden)


def test_v2_database_is_isolated_from_legacy_tables():
    text = Path("v2_db_namespace.py").read_text()
    assert 'PG_SCHEMA = "emptychair_v2"' in text
    assert "search_path" in text
    assert "CREATE SCHEMA IF NOT EXISTS" in text


def test_v2_offer_delivery_is_transport_aware():
    text = Path("v2_offer_delivery.py").read_text()
    assert "offer.delivery.accepted" in text
    assert "offer.delivery_failed" in text
    assert "status='RETRY'" in text
    assert "MAX_DELIVERY_ATTEMPTS = 3" in text
    assert "core.send_next_offer = send_next_offer" in text
    assert "_repair_pre_fix_offers()" in text


def test_v2_is_sms_only():
    text = Path("v2_sms_only.py").read_text()
    assert "core.send_email = send_email_disabled" in text
    assert "core.send_digests_if_due = send_digests_if_due_sms" in text
    assert "EMPTY CHAIR // WEEK" in text
    assert "EMPTY CHAIR // MONTH" in text
    assert "core.send_sms(artist.get(\"phone\"), body)" in text


def test_v2_auth_contract_present():
    text = Path("v2_auth.py").read_text()
    assert "CONTINUE WITH APPLE" in text
    assert "CONTINUE WITH GOOGLE" in text
    assert "CONTINUE WITH PHONE" in text
    assert "/auth/phone" in text
    assert "/auth/apple/callback" in text
    assert "/auth/google/login/callback" in text
    assert "openid email profile" in text
    assert "PyJWKClient" in text
    assert "APPLE // NEEDS CONFIG" not in text


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


def test_native_mobile_contract_present():
    native = Path("v2_native_calendar.py").read_text()
    auth = Path("v2_native_auth.py").read_text()
    finalize = Path("v2_native_finalize_bridge.py").read_text()
    ios = Path("ios/EmptyChair/App.swift").read_text()
    android = Path("android/app/src/main/java/com/tryemptychair/MainActivity.kt").read_text()
    manifest = Path("android/app/src/main/AndroidManifest.xml").read_text()

    assert "/native/calendar/sync" in native
    assert "/native/calendar/ack/{command_id}" in native
    assert 'platform not in ("ios","android")' in native
    assert "/native/auth/start" in auth and "/native/auth/verify" in auth
    assert "calendar.native_write_queued" in finalize
    assert "pending:" in finalize
    assert "EventKit" in ios and "BGTaskScheduler" in ios and "Keychain" in ios
    assert "CalendarContract" in android and "PeriodicWorkRequestBuilder" in android and "BiometricPrompt" in android
    assert "READ_CALENDAR" in manifest and "WRITE_CALENDAR" in manifest and "USE_BIOMETRIC" in manifest
    assert Path("ios/project.yml").exists()
    assert Path("android/app/build.gradle.kts").exists()
    assert Path(".github/workflows/native-builds.yml").exists()
