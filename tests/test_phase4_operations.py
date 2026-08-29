from pathlib import Path
from unittest.mock import patch

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
        _seed_operations_data()
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
        export = client.get("/operations/export.csv")
    assert page.status_code == 200
    assert "Ops Customer" in page.text
    assert "Reopen time" in page.text
    assert "Private Customer" not in page.text
    assert export.status_code == 200
    assert "book_p4" in export.text
    assert "other_booking" not in export.text


def test_cancel_booking_reopens_slot():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_operations_data()
        with patch.object(core, "start_recovery_campaign", return_value=None):
            response = client.post("/operations/bookings/book_p4/cancel", follow_redirects=False)
    assert response.status_code == 303
    conn = core.connect()
    try:
        booking = core.db_fetchone(conn, "SELECT status FROM bookings WHERE id='book_p4'")
        opening = core.db_fetchone(conn, "SELECT status,booking_id FROM openings WHERE id='open_p4'")
        offer = core.db_fetchone(conn, "SELECT status FROM offers WHERE id='offer_p4'")
    finally:
        conn.close()
    assert booking["status"] == "CANCELLED"
    assert opening["status"] == "OPEN"
    assert opening["booking_id"] is None
    assert offer["status"] == "CANCELLED"


def test_current_navigation_architecture_is_present():
    sidebar = Path("templates/_sidebar.html").read_text()
    mobile_css = Path("static/mobile-nav.css").read_text()
    for label in ["Shop Intelligence", "Demand Graph", "Demand Engine", "M4 Intelligence", "Openings", "Calendar", "Concierge Leads"]:
        assert label in sidebar
    assert ".sidebar-nav>.mobile-overflow" in mobile_css
    assert "nth-child" not in mobile_css
    assert "grid-template-columns:repeat(4" in mobile_css


def test_current_shop_intelligence_and_calendar_language():
    dashboard = Path("templates/dashboard_v2.html").read_text()
    calendar = Path("templates/bookings.html").read_text()
    operations = Path("templates/operations.html").read_text()
    assert '<div class="page-title">Shop Intelligence</div>' in dashboard
    assert "Recovered Revenue" in dashboard
    assert "What Empty Chair is working" in dashboard
    assert '<div class="page-title">Calendar</div>' in calendar
    assert "where Empty Chair is actively working" in calendar
    assert '<div class="page-title">Operations</div>' in operations
    assert "Measured revenue from confirmed outcomes" in operations


def test_complete_snapshot_failure_renders_safe_mode_instead_of_500():
    with TestClient(app) as client:
        create_test_account(client)
        with patch("pilot_operations._snapshot", side_effect=RuntimeError("production database mismatch")):
            response = client.get("/operations")
    assert response.status_code == 200
    assert '<div class="page-title">Operations</div>' in response.text
    assert "Operations loaded in safe mode" in response.text
