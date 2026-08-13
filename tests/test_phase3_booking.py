from unittest.mock import patch
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import google_integration
from bootstrap import app
from tests.test_smoke import core, create_test_account

TEST_DB = Path("test_empty_chair.db")

@pytest.fixture(autouse=True)
def fresh_phase3_database():
    if TEST_DB.exists(): TEST_DB.unlink()
    core.init_db()
    google_integration._ensure_schema()
    yield
    if TEST_DB.exists(): TEST_DB.unlink()

def _seed_claim():
    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT id FROM shops LIMIT 1")
        artist = core.db_fetchone(conn, "SELECT id FROM artists LIMIT 1")
        now = core.now_iso()
        if not artist:
            core.db_execute(conn, "INSERT INTO artists(id,shop_id,name,styles,services,active) VALUES ('artist_p3',?,'Pilot Artist','','tattoo',1)", (shop["id"],))
            artist = {"id": "artist_p3"}
        core.db_execute(conn, "INSERT INTO customers(id,shop_id,name,phone,email,communication_consent,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?)", ("cust_p3",shop["id"],"Pilot Customer","+17065550155","pilot@gmail.com",now,now))
        core.db_execute(conn, "INSERT INTO openings(id,shop_id,artist_id,date,start_time,end_time,service,price,status,created_at,expires_at,booking_id) VALUES (?,?,?,'2026-08-25','14:00','16:00','tattoo',400,'CLAIMED',?,?,?)", ("open_p3",shop["id"],artist["id"],now,now,"book_p3"))
        core.db_execute(conn, "INSERT INTO bookings(id,opening_id,customer_id,artist_id,status,amount,booked_at) VALUES ('book_p3','open_p3','cust_p3',?,'AWAITING_CONFIRMATION',400,NULL)", (artist["id"],))
        conn.commit()
        return shop["id"], artist["id"]
    finally: conn.close()

def test_confirmation_requires_authentication():
    with TestClient(app) as client:
        response = client.post("/bookings/book_p3/confirm", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login")

def test_shop_confirms_provisional_claim():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_claim()
        with patch.object(google_integration, "calendar_user_for_artist", return_value=None):
            response = client.post("/bookings/book_p3/confirm", follow_redirects=False)
        assert response.status_code == 303
        conn = core.connect()
        try:
            booking = core.db_fetchone(conn, "SELECT status,booked_at FROM bookings WHERE id='book_p3'")
            opening = core.db_fetchone(conn, "SELECT status FROM openings WHERE id='open_p3'")
        finally: conn.close()
        assert booking["status"] == "CONFIRMED"
        assert booking["booked_at"]
        assert opening["status"] == "BOOKED"


def test_confirmed_booking_visually_fills_calendar():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_claim()
        with patch.object(google_integration, "calendar_user_for_artist", return_value=None):
            client.post("/bookings/book_p3/confirm", follow_redirects=False)
        conn = core.connect()
        try:
            shop = core.db_fetchone(conn, "SELECT id FROM shops LIMIT 1")
            now = core.now_iso()
            core.db_execute(conn, "INSERT INTO openings(id,shop_id,artist_id,date,start_time,end_time,service,price,status,created_at,expires_at) VALUES ('open_needs',?,?,'2026-08-26','10:00','12:00','tattoo',300,'OPEN',?,?)", (shop["id"], "artist_p3", now, now))
            core.db_execute(conn, "INSERT INTO openings(id,shop_id,artist_id,date,start_time,end_time,service,price,status,created_at,expires_at) VALUES ('open_working',?,?,'2026-08-27','12:00','14:00','tattoo',350,'RECOVERY_ACTIVE',?,?)", (shop["id"], "artist_p3", now, now))
            conn.commit()
        finally:
            conn.close()

        with patch.object(google_integration, "external_calendar_events_for_shop", return_value=[{"id":"external_1","artist_name":"Pilot Artist","start":"2026-08-28T09:00:00-04:00","end":"2026-08-28T11:00:00-04:00","html_link":"https://calendar.google.com/event"}]):
            response = client.get("/bookings?month=2026-08")

        assert response.status_code == 200
        assert 'aria-label="Appointment status calendar"' in response.text
        assert "August 2026" in response.text
        assert "Pilot Artist" in response.text
        assert "Pilot Customer" in response.text
        assert "14:00–16:00" in response.text
        assert "Confirmed revenue" in response.text
        assert "Needs filling" in response.text
        assert "Empty Chair working" in response.text
        assert 'class="calendar-event open"' in response.text
        assert 'class="calendar-event working"' in response.text
        assert 'class="calendar-event filled"' in response.text
        assert 'class="calendar-event external"' in response.text
        assert "Google Calendar busy" in response.text

def test_reject_reopens_slot():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_claim()
        with patch.object(core, "start_recovery_campaign", return_value=None):
            response = client.post("/bookings/book_p3/reject", follow_redirects=False)
        assert response.status_code == 303
        conn = core.connect()
        try:
            booking = core.db_fetchone(conn, "SELECT status FROM bookings WHERE id='book_p3'")
            opening = core.db_fetchone(conn, "SELECT status,booking_id FROM openings WHERE id='open_p3'")
        finally: conn.close()
        assert booking["status"] == "REJECTED"
        assert opening["status"] == "OPEN"
        assert opening["booking_id"] is None

def test_artist_calendar_mapping_is_specific():
    with TestClient(app) as client:
        create_test_account(client)
        _, artist_id = _seed_claim()
        conn = core.connect()
        try:
            user = core.db_fetchone(conn, "SELECT id FROM users LIMIT 1")
            core.db_execute(conn, "INSERT INTO artist_calendar_connections(artist_id,user_id,connected_at) VALUES (?,?,?)", (artist_id,user["id"],core.now_iso()))
            conn.commit()
        finally: conn.close()
        assert google_integration.calendar_user_for_artist(artist_id) == user["id"]
