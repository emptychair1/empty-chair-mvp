import hashlib
import hmac
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import stripe_deposits
from bootstrap import app
from tests.test_smoke import core, create_test_account


TEST_DB = Path("test_empty_chair.db")


@pytest.fixture(autouse=True)
def fresh_stripe_database():
    if TEST_DB.exists():
        TEST_DB.unlink()
    core.init_db()
    stripe_deposits.ensure_schema()
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()


def _seed_deposit_booking():
    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT id FROM shops LIMIT 1")
        artist = core.db_fetchone(conn, "SELECT id FROM artists LIMIT 1")
        if not artist:
            core.db_execute(conn, "INSERT INTO artists(id,shop_id,name,styles,services,active) VALUES ('stripe_artist',?,'Deposit Artist','','tattoo',1)", (shop["id"],))
            artist = {"id": "stripe_artist"}
        now = core.now_iso()
        core.db_execute(conn, "INSERT INTO customers(id,shop_id,name,phone,email,communication_consent,created_at,updated_at) VALUES ('stripe_customer',?,'Deposit Customer','+17065550111','deposit@example.net',1,?,?)", (shop["id"], now, now))
        core.db_execute(conn, "INSERT INTO openings(id,shop_id,artist_id,date,start_time,end_time,service,price,status,created_at,expires_at,booking_id) VALUES ('stripe_opening',?,?,'2026-09-10','13:00','15:00','tattoo',400,'CLAIMED',?,?,'stripe_booking')", (shop["id"], artist["id"], now, now))
        core.db_execute(conn, """INSERT INTO bookings(id,opening_id,customer_id,artist_id,status,amount,deposit_amount,deposit_status) VALUES ('stripe_booking','stripe_opening','stripe_customer',?,'PAYMENT_REQUIRED',400,100,'REQUIRED')""", (artist["id"],))
        conn.commit()
    finally:
        conn.close()


def test_owner_can_configure_deposit_amount():
    with TestClient(app) as client:
        create_test_account(client)
        response = client.post("/settings", data={"name":"Test Tattoo Studio","email":"","phone":"","booking_url":"","timezone_name":"America/New_York","deposits_enabled":"1","default_deposit_amount":"100"}, follow_redirects=False)
        assert response.status_code == 303
        conn = core.connect()
        try:
            shop = core.db_fetchone(conn, "SELECT deposits_enabled,default_deposit_amount FROM shops LIMIT 1")
        finally:
            conn.close()
        assert shop["deposits_enabled"] == 1
        assert shop["default_deposit_amount"] == 100


def test_customer_is_redirected_to_hosted_stripe_checkout():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_deposit_booking()
        session = {"id":"cs_test_deposit","url":"https://checkout.stripe.com/c/pay/test"}
        with patch.object(stripe_deposits, "STRIPE_SECRET_KEY", "sk_test_value"), patch.object(stripe_deposits, "_stripe_post", return_value=session) as create:
            response = client.post("/booking/stripe_booking/deposit", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == session["url"]
        fields = create.call_args.args[1]
        assert fields["line_items[0][price_data][unit_amount]"] == "10000"
        assert fields["metadata[booking_id]"] == "stripe_booking"


def test_signed_paid_webhook_unlocks_owner_confirmation_and_is_idempotent():
    with TestClient(app) as client:
        create_test_account(client)
        _seed_deposit_booking()
        event = {"id":"evt_deposit_paid","type":"checkout.session.completed","data":{"object":{"id":"cs_paid","payment_status":"paid","payment_intent":"pi_paid","metadata":{"booking_id":"stripe_booking"}}}}
        payload = json.dumps(event, separators=(",", ":")).encode()
        timestamp = int(time.time())
        secret = "whsec_test"
        digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
        headers = {"stripe-signature":f"t={timestamp},v1={digest}","content-type":"application/json"}
        with patch.object(stripe_deposits, "STRIPE_WEBHOOK_SECRET", secret):
            first = client.post("/webhooks/stripe", content=payload, headers=headers)
            second = client.post("/webhooks/stripe", content=payload, headers=headers)
        assert first.status_code == 200
        assert second.json()["duplicate"] is True
        conn = core.connect()
        try:
            booking = core.db_fetchone(conn, "SELECT status,deposit_status,deposit_paid_at,stripe_payment_intent_id FROM bookings WHERE id='stripe_booking'")
        finally:
            conn.close()
        assert booking["status"] == "AWAITING_CONFIRMATION"
        assert booking["deposit_status"] == "PAID"
        assert booking["deposit_paid_at"]
        assert booking["stripe_payment_intent_id"] == "pi_paid"


def test_unsigned_webhook_is_rejected():
    with TestClient(app) as client:
        with patch.object(stripe_deposits, "STRIPE_WEBHOOK_SECRET", "whsec_test"):
            response = client.post("/webhooks/stripe", content=b"{}", headers={"content-type":"application/json"})
        assert response.status_code == 400
