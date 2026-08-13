import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import delivery_safety
from bootstrap import app
from tests.test_smoke import core, create_test_account

TEST_DB = Path("test_empty_chair.db")

@pytest.fixture(autouse=True)
def fresh_phase2_database():
    if TEST_DB.exists(): TEST_DB.unlink()
    core.init_db()
    delivery_safety.ensure_schema()
    yield
    if TEST_DB.exists(): TEST_DB.unlink()

def test_placeholder_emails_are_not_deliverable():
    assert delivery_safety.valid_email("real@gmail.com")
    assert not delivery_safety.valid_email("sarah@example.com")
    assert not delivery_safety.valid_email("broken")

def test_queue_requires_a_live_channel(monkeypatch):
    customer = {"email": "real@gmail.com", "phone": "+17065550100"}
    monkeypatch.setenv("EMPTY_CHAIR_EMAIL_LIVE", "false")
    monkeypatch.setenv("EMPTY_CHAIR_SMS_LIVE", "false")
    assert not delivery_safety.eligible_for_offer(customer)
    monkeypatch.setenv("EMPTY_CHAIR_EMAIL_LIVE", "true")
    assert delivery_safety.eligible_for_offer(customer)

def test_import_disables_placeholder_only_contact():
    with TestClient(app) as client:
        create_test_account(client)
        csv_data = "name,phone,email,communication_consent\nDemo Person,5550101,demo@example.com,1\n"
        response = client.post("/import/customers", files={"file": ("customers.csv", io.BytesIO(csv_data.encode()), "text/csv")})
        assert response.status_code == 200
        conn = core.connect()
        try: customer = core.db_fetchone(conn, "SELECT * FROM customers WHERE name = 'Demo Person'")
        finally: conn.close()
        assert customer["communication_consent"] == 0
        assert customer["email"] is None

def test_shop_suppression_disables_contact():
    with TestClient(app) as client:
        create_test_account(client)
        conn = core.connect()
        try:
            shop = core.db_fetchone(conn, "SELECT id FROM shops LIMIT 1")
            now = core.now_iso()
            core.db_execute(conn, "INSERT INTO customers(id, shop_id, name, phone, email, communication_consent, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)", ("cust_suppress", shop["id"], "Suppress Me", "+17065550122", "real@gmail.com", now, now))
            conn.commit()
        finally: conn.close()
        response = client.post("/customers/cust_suppress/suppress", follow_redirects=False)
        assert response.status_code == 303
        conn = core.connect()
        try:
            customer = core.db_fetchone(conn, "SELECT communication_consent FROM customers WHERE id = 'cust_suppress'")
            suppressed = delivery_safety.is_suppressed(conn, "cust_suppress")
        finally: conn.close()
        assert customer["communication_consent"] == 0
        assert suppressed

def test_test_email_rejects_placeholder():
    with TestClient(app) as client:
        create_test_account(client)
        response = client.post("/settings/test-email", data={"email": "demo@example.com"}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/settings?test_email=invalid"
