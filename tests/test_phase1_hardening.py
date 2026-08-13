import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from tests.test_smoke import core, create_test_account
from fastapi.testclient import TestClient

import fill_chairs_flow
import notifications
import pilot
import pilot_worker
from bootstrap import app


TEST_DB = Path("test_empty_chair.db")


@pytest.fixture(autouse=True)
def fresh_phase1_database():
    if TEST_DB.exists():
        TEST_DB.unlink()
    core.init_db()
    pilot._ensure_autopilot_schema()
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()


def test_demo_onboarding_creates_valid_customer_timestamps():
    with TestClient(app) as client:
        create_test_account(client)
        response = client.post("/setup/demo", follow_redirects=False)
        assert response.status_code == 303

        conn = core.connect()
        try:
            customers = core.db_fetchall(
                conn,
                "SELECT created_at, updated_at FROM customers",
            )
        finally:
            conn.close()

        assert customers
        assert all(customer["created_at"] for customer in customers)
        assert all(customer["updated_at"] for customer in customers)


def test_delivery_retries_and_records_attempt_counts():
    customer = {
        "name": "Retry Customer",
        "phone": "+17065550100",
        "email": "retry@example.com",
    }
    opening = {
        "style": "traditional",
        "date": "2026-08-20",
        "start_time": "14:00",
        "price": 300,
    }
    sms_results = iter([False, False, True])
    recorded = []

    with (
        patch.object(notifications, "SMS_LIVE", True),
        patch.object(notifications, "EMAIL_LIVE", True),
        patch.object(notifications, "DELIVERY_ATTEMPTS", 3),
        patch.object(notifications, "_send_text", side_effect=lambda *_: next(sms_results)),
        patch.object(notifications, "send_offer_email", return_value=False),
        patch.object(notifications.time, "sleep"),
        patch.object(
            notifications.core,
            "event",
            side_effect=lambda *args: recorded.append(args),
        ),
    ):
        assert notifications.send_offer_multichannel(customer, opening, "offer_retry")

    metadata = json.loads(recorded[-1][3])
    assert metadata["sms"] is True
    assert metadata["sms_attempts"] == 3
    assert metadata["email_attempts"] == 3


def test_worker_expires_due_offers_and_advances_active_shops():
    due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    conn = core.connect()
    try:
        core.db_execute(
            conn,
            """
            INSERT INTO offers(
                id, opening_id, customer_id, score, rank,
                channel, expires_at, status
            ) VALUES (?, ?, ?, 1, 1, 'email', ?, 'SENT')
            """,
            ("offer_due", "opening_missing", "customer_missing", due),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()

    with (
        patch.object(pilot_worker, "expire_due_offers", return_value=1) as expire,
        patch.object(pilot_worker, "active_shop_ids", return_value=["shop_1", "shop_2"]),
        patch.object(fill_chairs_flow, "_activate_shop") as activate,
    ):
        pilot_worker.run_tick()

    expire.assert_called_once_with()
    assert [call.args[0] for call in activate.call_args_list] == ["shop_1", "shop_2"]


def test_fill_chairs_snapshot_exposes_delivery_failure():
    with TestClient(app) as client:
        create_test_account(client)
        conn = core.connect()
        try:
            shop = core.db_fetchone(conn, "SELECT id FROM shops LIMIT 1")
            artist = core.db_fetchone(conn, "SELECT id FROM artists LIMIT 1")
            if not artist:
                core.db_execute(
                    conn,
                    "INSERT INTO artists(id, shop_id, name, styles, services, active) VALUES (?, ?, ?, '', 'tattoo', 1)",
                    ("artist_delivery", shop["id"], "Delivery Artist"),
                )
            now = core.now_iso()
            core.db_execute(
                conn,
                """
                INSERT INTO customers(
                    id, shop_id, name, phone, communication_consent,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                ("customer_delivery", shop["id"], "Delivery Customer", "+17065550111", now, now),
            )
            core.db_execute(
                conn,
                """
                INSERT INTO openings(
                    id, shop_id, artist_id, date, start_time, end_time,
                    service, price, status, created_at, expires_at
                ) VALUES (?, ?, ?, '2026-08-20', '14:00', '16:00',
                    'tattoo', 300, 'RECOVERY_ACTIVE', ?, ?)
                """,
                ("opening_delivery", shop["id"], "artist_delivery", now, now),
            )
            core.db_execute(
                conn,
                """
                INSERT INTO offers(
                    id, opening_id, customer_id, score, rank,
                    channel, expires_at, status
                ) VALUES (?, ?, ?, 1, 1, 'email', ?, 'SENT')
                """,
                ("offer_delivery", "opening_delivery", "customer_delivery", now),
            )
            core.db_execute(
                conn,
                """
                INSERT INTO events(event_type, entity_type, entity_id, metadata, created_at)
                VALUES ('offer.delivery', 'offer', ?, ?, ?)
                """,
                ("offer_delivery", json.dumps({"sms": False, "email": False, "email_attempts": 3, "error": "provider unavailable"}), now),
            )
            conn.commit()
            snapshot = fill_chairs_flow._database_snapshot(shop["id"])
        finally:
            conn.close()

    assert snapshot["recent_deliveries"][0]["success"] is False
    assert snapshot["recent_deliveries"][0]["attempts"] == 3
    assert snapshot["recent_deliveries"][0]["error"] == "provider unavailable"
