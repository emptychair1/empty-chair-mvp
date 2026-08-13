from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

import google_integration
import pilot
from bootstrap import app
from tests.test_smoke import core, create_test_account


TEST_DB = Path("test_empty_chair.db")


@pytest.fixture(autouse=True)
def fresh_phase4_database():
    if TEST_DB.exists():
        TEST_DB.unlink()
    core.init_db()
    google_integration._ensure_schema()
    pilot._ensure_autopilot_schema()
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()


def _seed_operations_data():
    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT id FROM shops LIMIT 1")
        now = core.now_iso()
        core.db_execute(conn, "INSERT INTO artists(id,shop_id,name,styles,services,active) VALUES ('artist_p4',?,'Ops Artist','','tattoo',1)", (shop["id"],))
        core.db_execute(conn, "INSERT INTO customers(id,shop_id,name,phone,email,communication_consent,created_at,updated_at) VALUES ('cust_p4',?,'Ops Customer','+17065550123','ops@example.com',1,?,?)", (shop["id"], now, now))
        core.db_execute(conn, "INSERT INTO openings(id,shop_id,artist_id,date,start_time,end_time,service,price,status,created_at,expires_at,booking_id) VALUES ('open_p4',?,'artist_p4','2026-08-30','10:00','12:00','tattoo',500,'BOOKED',?,?,'book_p4')", (shop["id"], now, now))
        core.db_execute(conn, "INSERT INTO offers(id,opening_id,customer_id,score,rank,expires_at,status) VALUES ('offer_p4','open_p4','cust_p4',100,1,?,'SENT')", (now,))
        core.db_execute(conn, "INSERT INTO bookings(id,opening_id,customer_id,artist_id,status,amount,booked_at) VALUES ('book_p4','open_p4','cust_p4','artist_p4','CONFIRMED',500,?)", (now,))
        core.db_execute(conn, "INSERT INTO events(event_type,entity_type,entity_id,metadata,created_at) VALUES ('offer.delivery','offer','offer_p4',?,?)", ('{"sms": false, "email": false}', now))
        conn.commit()
        return shop["id"]
    finally:
        conn.close()


def test_operations_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/operations", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login")


def test_operations_page_and_export_are_shop_scoped():
    with TestClient(app) as client:
        create_test_account(client)
        shop_id = _seed_operations_data()
        conn = core.connect()
        try:
            now = core.now_iso()
            core.db_execute(conn, "INSERT INTO shops(id,name,created_at) VALUES ('other_shop','Other Studio',?)", (now,))
            core.db_execute(conn, "INSERT INTO artists(id,shop_id,name,styles,services,active) VALUES ('other_artist','other_shop','Other Artist','','tattoo',1)")
            core.db_execute(conn, "INSERT INTO customers(id,shop_id,name,phone,email,created_at,updated_at) VALUES ('other_customer','other_shop','Private Customer','1','private@example.com',?,?)", (now, now))
            core.db_execute(conn, "INSERT INTO openings(id,shop_id,artist_id,date,start_time,service,price,status,created_at,expires_at) VALUES ('other_open','other_shop','other_artist','2026-09-01','09:00','tattoo',900,'BOOKED',?,?)", (now, now))
            core.db_execute(conn, "INSERT INTO bookings(id,opening_id,customer_id,artist_id,status,amount) VALUES ('other_booking','other_open','other_customer','other_artist','CONFIRMED',900)")
            conn.commit()
        finally:
            conn.close()
        with patch.object(google_integration, "artist_calendar_connected", return_value=False):
            page = client.get("/operations")
        assert page.status_code == 200
        assert "Ops Customer" in page.text
        assert "Cancel & Reopen" in page.text
        assert "Test Tattoo Studio" in page.text
        assert "Private Customer" not in page.text
        export = client.get("/operations/export.csv")
        assert export.status_code == 200
        assert "book_p4" in export.text
        assert "other_booking" not in export.text
        assert shop_id


def test_retry_only_sends_still_active_offer():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_operations_data()
        with patch("pilot_operations.notifications.send_offer_multichannel", return_value=True) as sender:
            response = client.post("/operations/offers/offer_p4/retry", follow_redirects=False)
        assert response.status_code == 303
        sender.assert_called_once()
        conn = core.connect()
        try:
            core.db_execute(conn, "UPDATE offers SET status='EXPIRED' WHERE id='offer_p4'")
            conn.commit()
        finally:
            conn.close()
        response = client.post("/operations/offers/offer_p4/retry", follow_redirects=False)
        assert response.status_code == 409


def test_cancel_booking_reopens_slot_and_invalidates_offer():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_operations_data()
        with patch.object(core, "start_recovery_campaign", return_value=None):
            response = client.post("/operations/bookings/book_p4/cancel", follow_redirects=False)
        assert response.status_code == 303
        conn = core.connect()
        try:
            booking = core.db_fetchone(conn, "SELECT status,cancelled_at FROM bookings WHERE id='book_p4'")
            opening = core.db_fetchone(conn, "SELECT status,booking_id FROM openings WHERE id='open_p4'")
            offer = core.db_fetchone(conn, "SELECT status FROM offers WHERE id='offer_p4'")
        finally:
            conn.close()
        assert booking["status"] == "CANCELLED"
        assert booking["cancelled_at"]
        assert opening["status"] == "OPEN"
        assert opening["booking_id"] is None
        assert offer["status"] == "CANCELLED"


def test_cancel_booking_removes_managed_google_event():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_operations_data()
        conn = core.connect()
        try:
            user = core.db_fetchone(conn, "SELECT id FROM users LIMIT 1")
        finally:
            conn.close()
        google_integration.remember_booking_event("book_p4", user["id"], "google_event_1")

        with patch.object(google_integration, "_access_token", return_value="token"), patch.object(google_integration, "_authorized_request", return_value={}) as request_google, patch.object(core, "start_recovery_campaign", return_value=None):
            response = client.post("/operations/bookings/book_p4/cancel", follow_redirects=False)

        assert response.status_code == 303
        request_google.assert_called_once()
        assert request_google.call_args.kwargs["method"] == "DELETE"
        assert google_integration.booking_event("book_p4") is None


def test_google_side_cancellation_reopens_empty_chair_slot():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_operations_data()
        conn = core.connect()
        try:
            user = core.db_fetchone(conn, "SELECT id FROM users LIMIT 1")
        finally:
            conn.close()
        google_integration.remember_booking_event("book_p4", user["id"], "deleted_google_event")
        missing = HTTPError("https://google.test/event", 404, "Not found", None, None)

        with patch.object(google_integration, "_access_token", return_value="token"), patch.object(google_integration, "_authorized_request", side_effect=missing), patch.object(core, "start_recovery_campaign", return_value=None) as recovery:
            reopened = google_integration.reconcile_deleted_booking_events()

        assert reopened == 1
        recovery.assert_called_once_with("open_p4")
        conn = core.connect()
        try:
            booking = core.db_fetchone(conn, "SELECT status FROM bookings WHERE id='book_p4'")
            opening = core.db_fetchone(conn, "SELECT status,booking_id FROM openings WHERE id='open_p4'")
        finally:
            conn.close()
        assert booking["status"] == "CANCELLED"
        assert opening["status"] == "OPEN"
        assert opening["booking_id"] is None


def test_google_side_reschedule_updates_empty_chair_calendar_time():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_operations_data()
        conn = core.connect()
        try:
            user = core.db_fetchone(conn, "SELECT id FROM users LIMIT 1")
        finally:
            conn.close()
        google_integration.remember_booking_event("book_p4", user["id"], "moved_google_event")
        moved_event = {
            "id": "moved_google_event",
            "status": "confirmed",
            "start": {"dateTime": "2026-08-31T15:00:00-04:00"},
            "end": {"dateTime": "2026-08-31T17:00:00-04:00"},
        }

        with patch.object(google_integration, "_access_token", return_value="token"), patch.object(google_integration, "_authorized_request", return_value=moved_event):
            reopened = google_integration.reconcile_deleted_booking_events()

        assert reopened == 0
        conn = core.connect()
        try:
            opening = core.db_fetchone(conn, "SELECT date,start_time,end_time,status FROM openings WHERE id='open_p4'")
        finally:
            conn.close()
        assert opening["date"] == "2026-08-31"
        assert opening["start_time"] == "15:00"
        assert opening["end_time"] == "17:00"
        assert opening["status"] == "BOOKED"


def test_mobile_navigation_uses_explicit_overflow_items():
    sidebar = Path("templates/_sidebar.html").read_text()
    mobile_css = Path("static/mobile-nav.css").read_text()
    assert sidebar.count("mobile-overflow") == 4
    assert ".sidebar-nav > .mobile-overflow" in mobile_css
    assert "nth-child" not in mobile_css
    assert 'class="mobile-brand"' not in sidebar
    assert ".topbar::before" in mobile_css
    assert "empty-chair-logo.png" in mobile_css


def test_visual_polish_keeps_accessibility_guards():
    stylesheet = Path("static/style.css").read_text()
    assert ":focus-visible" in stylesheet
    assert "prefers-reduced-motion" in stylesheet
    assert "@media (hover: none)" in stylesheet


def test_owner_and_artist_value_hierarchy_is_explicit():
    dashboard = Path("templates/dashboard_v2.html").read_text()
    artists = Path("templates/artists.html").read_text()
    operations = Path("templates/operations.html").read_text()

    assert "Recovered revenue" in dashboard
    assert "Earning time available" in dashboard
    assert "Artists with earning time" in dashboard
    assert "Available earning time" in artists
    assert "slots to fill" in artists
    assert operations.index("Confirmed revenue") < operations.index("Confirmed bookings")
    assert "Action required" in operations


def test_optional_operations_panel_failure_does_not_take_down_page():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_operations_data()
        original = core.db_fetchall

        def fail_recent_only(conn, query, params=()):
            if "b.status IN ('CONFIRMED','COMPLETED','CANCELLED')" in query:
                raise RuntimeError("legacy production schema")
            return original(conn, query, params)

        with patch.object(core, "db_fetchall", side_effect=fail_recent_only), patch.object(google_integration, "artist_calendar_connected", return_value=False):
            response = client.get("/operations")
        assert response.status_code == 200
        assert "Pilot Operations" in response.text
        assert "No confirmed bookings yet." in response.text


def test_complete_snapshot_failure_renders_safe_mode_instead_of_500():
    with TestClient(app) as client:
        create_test_account(client)
        with patch("pilot_operations._snapshot", side_effect=RuntimeError("production database mismatch")):
            response = client.get("/operations")
        assert response.status_code == 200
        assert "Pilot Operations" in response.text
        assert "Operations loaded in safe mode" in response.text
