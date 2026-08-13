"""Contact validation, suppression, unsubscribe, and test delivery for Phase 2."""
import re
import os
from fastapi import Form, HTTPException, Request
from fastapi.responses import RedirectResponse
import app as core

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_RE = re.compile(r"^\+[1-9]\d{9,14}$")
PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "test.com"}

def valid_email(value):
    email = core.normalize_email(value)
    return bool(email and EMAIL_RE.fullmatch(email) and email.rsplit("@", 1)[-1] not in PLACEHOLDER_DOMAINS)

def valid_phone(value):
    return bool(PHONE_RE.fullmatch((value or "").strip()))

def contact_status(customer):
    email_ok = valid_email(customer["email"] if "email" in customer.keys() else None)
    phone_ok = valid_phone(customer["phone"] if "phone" in customer.keys() else None)
    return {"deliverable": email_ok or phone_ok, "email": email_ok, "phone": phone_ok, "reason": "" if email_ok or phone_ok else "Add a real email or an international-format phone number."}

def eligible_for_offer(customer):
    status = contact_status(customer)
    sms_live = os.getenv("EMPTY_CHAIR_SMS_LIVE", "false").lower() == "true"
    email_live = os.getenv("EMPTY_CHAIR_EMAIL_LIVE", "false").lower() == "true"
    return bool((status["phone"] and sms_live) or (status["email"] and email_live))

def ensure_schema():
    conn = core.connect()
    try:
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS customer_suppressions(customer_id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(customer_id) REFERENCES customers(id), FOREIGN KEY(shop_id) REFERENCES shops(id))""")
        conn.commit()
    finally: conn.close()

def is_suppressed(conn, customer_id):
    return bool(core.db_fetchone(conn, "SELECT customer_id FROM customer_suppressions WHERE customer_id = ?", (customer_id,)))

def _suppress(conn, customer_id, shop_id, reason):
    core.db_execute(conn, "DELETE FROM customer_suppressions WHERE customer_id = ?", (customer_id,))
    core.db_execute(conn, "INSERT INTO customer_suppressions(customer_id, shop_id, reason, created_at) VALUES (?, ?, ?, ?)", (customer_id, shop_id, reason, core.now_iso()))
    core.db_execute(conn, "UPDATE customers SET communication_consent = 0, updated_at = ? WHERE id = ?", (core.now_iso(), customer_id))

@core.app.post("/customers/{customer_id}/suppress")
def suppress_customer(request: Request, customer_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    conn = core.connect()
    try:
        customer = core.db_fetchone(conn, "SELECT id FROM customers WHERE id = ? AND shop_id = ?", (customer_id, user["shop_id"]))
        if not customer: raise HTTPException(404, "Customer not found")
        _suppress(conn, customer_id, user["shop_id"], "shop_suppressed"); conn.commit()
    finally: conn.close()
    return RedirectResponse("/customers", status_code=303)

@core.app.get("/offer/{offer_id}/unsubscribe")
def unsubscribe_offer(offer_id: str):
    conn = core.connect()
    try:
        row = core.db_fetchone(conn, "SELECT c.id AS customer_id, c.shop_id FROM offers o JOIN customers c ON c.id = o.customer_id WHERE o.id = ?", (offer_id,))
        if not row: raise HTTPException(404, "Offer not found")
        _suppress(conn, row["customer_id"], row["shop_id"], "customer_unsubscribed"); conn.commit()
    finally: conn.close()
    return RedirectResponse(f"/offer/{offer_id}?unsubscribed=1", status_code=303)

@core.app.post("/settings/test-email")
def test_email(request: Request, email: str = Form(...)):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    if not valid_email(email): return RedirectResponse("/settings?test_email=invalid", status_code=303)
    try: sent = core.send_email(email, "Empty Chair test email", "<h2>Your Empty Chair email delivery is working.</h2><p>You can safely test a real offer next.</p>")
    except Exception: sent = False
    core.event("delivery.test_email", "shop", user["shop_id"], "sent" if sent else "failed")
    return RedirectResponse(f"/settings?test_email={'sent' if sent else 'failed'}", status_code=303)

ensure_schema()
