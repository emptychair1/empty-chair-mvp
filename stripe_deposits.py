"""Stripe-hosted deposit collection for Empty Chair bookings."""

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

import app as core


STRIPE_API_BASE = "https://api.stripe.com/v1"
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_CURRENCY = os.getenv("STRIPE_CURRENCY", "usd").lower()
WEBHOOK_TOLERANCE_SECONDS = 300


def _columns(conn, table):
    if core.USE_POSTGRES:
        rows = core.db_fetchall(
            conn,
            "SELECT column_name FROM information_schema.columns WHERE table_name=?",
            (table,),
        )
        return {row["column_name"] for row in rows}
    return {row["name"] for row in core.db_fetchall(conn, f"PRAGMA table_info({table})")}


def ensure_schema():
    conn = core.connect()
    try:
        shop_columns = _columns(conn, "shops")
        if shop_columns and "deposits_enabled" not in shop_columns:
            core.db_execute(conn, "ALTER TABLE shops ADD COLUMN deposits_enabled INTEGER NOT NULL DEFAULT 0")
        if shop_columns and "default_deposit_amount" not in shop_columns:
            core.db_execute(conn, "ALTER TABLE shops ADD COLUMN default_deposit_amount REAL NOT NULL DEFAULT 0")
        if shop_columns and "stripe_account_id" not in shop_columns:
            core.db_execute(conn, "ALTER TABLE shops ADD COLUMN stripe_account_id TEXT")
        if shop_columns and "stripe_details_submitted" not in shop_columns:
            core.db_execute(conn, "ALTER TABLE shops ADD COLUMN stripe_details_submitted INTEGER NOT NULL DEFAULT 0")
        if shop_columns and "stripe_charges_enabled" not in shop_columns:
            core.db_execute(conn, "ALTER TABLE shops ADD COLUMN stripe_charges_enabled INTEGER NOT NULL DEFAULT 0")
        if shop_columns and "stripe_payouts_enabled" not in shop_columns:
            core.db_execute(conn, "ALTER TABLE shops ADD COLUMN stripe_payouts_enabled INTEGER NOT NULL DEFAULT 0")

        booking_columns = _columns(conn, "bookings")
        if booking_columns and "deposit_status" not in booking_columns:
            core.db_execute(conn, "ALTER TABLE bookings ADD COLUMN deposit_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED'")
        if booking_columns and "deposit_paid_at" not in booking_columns:
            core.db_execute(conn, "ALTER TABLE bookings ADD COLUMN deposit_paid_at TEXT")
        if booking_columns and "stripe_checkout_session_id" not in booking_columns:
            core.db_execute(conn, "ALTER TABLE bookings ADD COLUMN stripe_checkout_session_id TEXT")
        if booking_columns and "stripe_payment_intent_id" not in booking_columns:
            core.db_execute(conn, "ALTER TABLE bookings ADD COLUMN stripe_payment_intent_id TEXT")

        core.db_execute(
            conn,
            """
            CREATE TABLE IF NOT EXISTS stripe_webhook_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                processed_at TEXT NOT NULL
            )
            """,
        )
        conn.commit()
    finally:
        conn.close()


def configured():
    return bool(STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET)


def _stripe_post(path, fields, idempotency_key=None):
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("Stripe is not configured")
    headers = {
        "Authorization": f"Bearer {STRIPE_SECRET_KEY}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(
        STRIPE_API_BASE + path,
        data=urllib.parse.urlencode(fields).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Stripe request failed ({exc.code}): {detail[:500]}") from exc


def _stripe_get(path):
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("Stripe is not configured")
    request = urllib.request.Request(
        STRIPE_API_BASE + path,
        headers={"Authorization": f"Bearer {STRIPE_SECRET_KEY}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Stripe request failed ({exc.code}): {detail[:500]}") from exc


def _save_account_status(account):
    account_id = account.get("id")
    if not account_id:
        return
    conn = core.connect()
    try:
        core.db_execute(
            conn,
            """UPDATE shops SET stripe_details_submitted=?,stripe_charges_enabled=?,stripe_payouts_enabled=? WHERE stripe_account_id=?""",
            (
                1 if account.get("details_submitted") else 0,
                1 if account.get("charges_enabled") else 0,
                1 if account.get("payouts_enabled") else 0,
                account_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _owner_shop(request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return None, redirect
    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT * FROM shops WHERE id=?", (user["shop_id"],))
    finally:
        conn.close()
    return shop, None


@core.app.post("/settings/stripe/connect")
def connect_stripe_account(request: Request):
    shop, redirect = _owner_shop(request)
    if redirect:
        return redirect
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Stripe Connect is not configured")

    account_id = shop["stripe_account_id"]
    if not account_id:
        fields = {
            "type": "express",
            "country": "US",
            "business_profile[name]": shop["name"],
            "business_profile[product_description]": "Tattoo appointment deposits",
            "capabilities[card_payments][requested]": "true",
            "capabilities[transfers][requested]": "true",
            "metadata[shop_id]": shop["id"],
        }
        if shop["email"]:
            fields["email"] = shop["email"]
        account = _stripe_post("/accounts", fields, idempotency_key=f"empty-chair-shop-{shop['id']}")
        account_id = account["id"]
        conn = core.connect()
        try:
            core.db_execute(conn, "UPDATE shops SET stripe_account_id=? WHERE id=?", (account_id, shop["id"]))
            conn.commit()
        finally:
            conn.close()

    base_url = core.PUBLIC_BASE_URL.rstrip("/")
    link = _stripe_post(
        "/account_links",
        {
            "account": account_id,
            "refresh_url": f"{base_url}/settings/stripe/refresh",
            "return_url": f"{base_url}/settings/stripe/return",
            "type": "account_onboarding",
            "collection_options[fields]": "eventually_due",
        },
    )
    return RedirectResponse(link["url"], status_code=303)


@core.app.get("/settings/stripe/refresh")
def refresh_stripe_onboarding(request: Request):
    shop, redirect = _owner_shop(request)
    if redirect:
        return redirect
    if not shop["stripe_account_id"]:
        return RedirectResponse("/settings?stripe=not_connected", status_code=303)
    base_url = core.PUBLIC_BASE_URL.rstrip("/")
    link = _stripe_post(
        "/account_links",
        {
            "account": shop["stripe_account_id"],
            "refresh_url": f"{base_url}/settings/stripe/refresh",
            "return_url": f"{base_url}/settings/stripe/return",
            "type": "account_onboarding",
            "collection_options[fields]": "eventually_due",
        },
    )
    return RedirectResponse(link["url"], status_code=303)


@core.app.get("/settings/stripe/return")
def stripe_onboarding_return(request: Request):
    shop, redirect = _owner_shop(request)
    if redirect:
        return redirect
    if not shop["stripe_account_id"]:
        return RedirectResponse("/settings?stripe=not_connected", status_code=303)
    account = _stripe_get(f"/accounts/{urllib.parse.quote(shop['stripe_account_id'], safe='')}")
    _save_account_status(account)
    state = "ready" if account.get("charges_enabled") and account.get("payouts_enabled") else "incomplete"
    return RedirectResponse(f"/settings?stripe={state}", status_code=303)


@core.app.post("/settings/stripe/disconnect")
def disconnect_stripe_account(request: Request):
    shop, redirect = _owner_shop(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        core.db_execute(
            conn,
            """
            UPDATE shops
            SET stripe_account_id=NULL,
                stripe_details_submitted=0,
                stripe_charges_enabled=0,
                stripe_payouts_enabled=0,
                deposits_enabled=0
            WHERE id=?
            """,
            (shop["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    core.event(
        "stripe.account_disconnected",
        "shop",
        shop["id"],
        "Studio Stripe connection reset for reconnection.",
    )
    return RedirectResponse("/settings?stripe=disconnected", status_code=303)


@core.app.post("/settings/stripe/dashboard")
def open_stripe_dashboard(request: Request):
    shop, redirect = _owner_shop(request)
    if redirect:
        return redirect
    if not shop["stripe_account_id"]:
        raise HTTPException(409, "Stripe account is not connected")
    link = _stripe_post(f"/accounts/{urllib.parse.quote(shop['stripe_account_id'], safe='')}/login_links", {})
    return RedirectResponse(link["url"], status_code=303)


def _booking(booking_id):
    conn = core.connect()
    try:
        return core.db_fetchone(
            conn,
            """
            SELECT b.*,c.email AS customer_email,c.name AS customer_name,
                   o.date,o.start_time,a.name AS artist_name,s.name AS shop_name,
                   s.stripe_account_id,s.stripe_charges_enabled,s.stripe_payouts_enabled
            FROM bookings b
            JOIN customers c ON c.id=b.customer_id
            JOIN openings o ON o.id=b.opening_id
            JOIN artists a ON a.id=b.artist_id
            JOIN shops s ON s.id=o.shop_id
            WHERE b.id=?
            """,
            (booking_id,),
        )
    finally:
        conn.close()


@core.app.post("/booking/{booking_id}/deposit")
def create_deposit_checkout(booking_id: str):
    booking = _booking(booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")
    if booking["deposit_status"] == "PAID":
        return RedirectResponse(f"/booking/{booking_id}", status_code=303)
    if booking["status"] != "PAYMENT_REQUIRED" or float(booking["deposit_amount"] or 0) <= 0:
        raise HTTPException(409, "This booking does not require a deposit")
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Deposit payments are not configured yet")
    if not booking["stripe_account_id"] or not booking["stripe_charges_enabled"]:
        raise HTTPException(503, "This shop has not finished connecting Stripe")

    amount_cents = int(round(float(booking["deposit_amount"]) * 100))
    base_url = core.PUBLIC_BASE_URL.rstrip("/")
    fields = {
        "mode": "payment",
        "success_url": f"{base_url}/booking/{booking_id}?deposit=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base_url}/booking/{booking_id}?deposit=cancelled",
        "client_reference_id": booking_id,
        "customer_email": booking["customer_email"] or "",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": STRIPE_CURRENCY,
        "line_items[0][price_data][unit_amount]": str(amount_cents),
        "line_items[0][price_data][product_data][name]": f"Deposit · {booking['artist_name']}",
        "line_items[0][price_data][product_data][description]": f"{booking['date']} at {booking['start_time']} · {booking['shop_name']}",
        "metadata[booking_id]": booking_id,
        "payment_intent_data[metadata][booking_id]": booking_id,
        "payment_intent_data[transfer_data][destination]": booking["stripe_account_id"],
        "payment_intent_data[on_behalf_of]": booking["stripe_account_id"],
    }
    session = _stripe_post(
        "/checkout/sessions",
        fields,
        idempotency_key=f"empty-chair-deposit-{booking_id}",
    )
    conn = core.connect()
    try:
        core.db_execute(
            conn,
            "UPDATE bookings SET stripe_checkout_session_id=?,deposit_status='PENDING' WHERE id=? AND deposit_status<>'PAID'",
            (session["id"], booking_id),
        )
        conn.commit()
    finally:
        conn.close()
    core.event("deposit.checkout_created", "booking", booking_id, session["id"])
    return RedirectResponse(session["url"], status_code=303)


def _verify_signature(payload, signature_header):
    if not STRIPE_WEBHOOK_SECRET or not signature_header:
        return False
    parts = {}
    for item in signature_header.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            parts.setdefault(key, []).append(value)
    try:
        timestamp = int(parts["t"][0])
    except (KeyError, ValueError):
        return False
    if abs(int(time.time()) - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(STRIPE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in parts.get("v1", []))


def _mark_deposit_paid(session):
    booking_id = (session.get("metadata") or {}).get("booking_id") or session.get("client_reference_id")
    if not booking_id or session.get("payment_status") != "paid":
        return False
    conn = core.connect()
    try:
        booking = core.db_fetchone(conn, "SELECT id,deposit_status FROM bookings WHERE id=?", (booking_id,))
        if not booking:
            return False
        core.db_execute(
            conn,
            """
            UPDATE bookings
            SET deposit_status='PAID',deposit_paid_at=?,
                stripe_checkout_session_id=?,stripe_payment_intent_id=?,
                status=CASE WHEN status='PAYMENT_REQUIRED' THEN 'AWAITING_CONFIRMATION' ELSE status END
            WHERE id=?
            """,
            (core.now_iso(), session.get("id"), session.get("payment_intent"), booking_id),
        )
        conn.commit()
    finally:
        conn.close()
    core.event("deposit.paid", "booking", booking_id, session.get("payment_intent"))
    return True


@core.app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    if not _verify_signature(payload, request.headers.get("stripe-signature", "")):
        raise HTTPException(400, "Invalid Stripe signature")
    try:
        event = json.loads(payload.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Invalid Stripe payload") from exc

    event_id = event.get("id")
    event_type = event.get("type", "")
    if not event_id:
        raise HTTPException(400, "Stripe event has no ID")
    conn = core.connect()
    try:
        if core.db_fetchone(conn, "SELECT event_id FROM stripe_webhook_events WHERE event_id=?", (event_id,)):
            return JSONResponse({"received": True, "duplicate": True})
    finally:
        conn.close()

    if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        _mark_deposit_paid(event.get("data", {}).get("object", {}))
    elif event_type == "account.updated":
        _save_account_status(event.get("data", {}).get("object", {}))

    conn = core.connect()
    try:
        core.db_execute(
            conn,
            "INSERT INTO stripe_webhook_events(event_id,event_type,processed_at) VALUES (?,?,?)",
            (event_id, event_type, core.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return JSONResponse({"received": True})


@core.app.on_event("startup")
def initialize_stripe_deposits():
    # The core startup creates base tables first; this then upgrades older pilots.
    ensure_schema()
