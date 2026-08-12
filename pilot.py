"""Pilot v1.0 readiness and outcome reporting for Empty Chair.

This module is intentionally additive. It does not replace the recovery or claim
flows; it gives a pilot shop one place to verify configuration, delivery health,
and measurable recovery outcomes.
"""

import json
from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core
import notifications


PILOT_VERSION = "1.0.0-pilot"


def _count(conn, query, params=()):
    row = core.db_fetchone(conn, query, params)
    if not row:
        return 0
    try:
        return int(row["total"] or 0)
    except (KeyError, TypeError):
        return int(row[0] or 0)


def _money(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _parse_metadata(value):
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _shop_snapshot(shop_id):
    conn = core.connect()
    try:
        shop = core.db_fetchone(
            conn,
            "SELECT * FROM shops WHERE id = ? LIMIT 1",
            (shop_id,),
        )

        artists = _count(
            conn,
            "SELECT COUNT(*) AS total FROM artists WHERE shop_id = ? AND active = 1",
            (shop_id,),
        )
        customers = _count(
            conn,
            "SELECT COUNT(*) AS total FROM customers WHERE shop_id = ?",
            (shop_id,),
        )
        consented_customers = _count(
            conn,
            """
            SELECT COUNT(*) AS total
            FROM customers
            WHERE shop_id = ? AND communication_consent = 1
            """,
            (shop_id,),
        )
        email_customers = _count(
            conn,
            """
            SELECT COUNT(*) AS total
            FROM customers
            WHERE shop_id = ?
              AND communication_consent = 1
              AND email IS NOT NULL
              AND TRIM(email) <> ''
            """,
            (shop_id,),
        )
        phone_customers = _count(
            conn,
            """
            SELECT COUNT(*) AS total
            FROM customers
            WHERE shop_id = ?
              AND communication_consent = 1
              AND phone IS NOT NULL
              AND TRIM(phone) <> ''
            """,
            (shop_id,),
        )
        openings = _count(
            conn,
            "SELECT COUNT(*) AS total FROM openings WHERE shop_id = ?",
            (shop_id,),
        )
        recovered = _count(
            conn,
            """
            SELECT COUNT(*) AS total
            FROM openings
            WHERE shop_id = ? AND status IN ('BOOKED','COMPLETED')
            """,
            (shop_id,),
        )
        offers = _count(
            conn,
            """
            SELECT COUNT(*) AS total
            FROM offers ofr
            JOIN openings o ON o.id = ofr.opening_id
            WHERE o.shop_id = ?
            """,
            (shop_id,),
        )
        claimed_offers = _count(
            conn,
            """
            SELECT COUNT(*) AS total
            FROM offers ofr
            JOIN openings o ON o.id = ofr.opening_id
            WHERE o.shop_id = ? AND ofr.status = 'CLAIMED'
            """,
            (shop_id,),
        )

        revenue_row = core.db_fetchone(
            conn,
            """
            SELECT COALESCE(SUM(price), 0) AS total
            FROM openings
            WHERE shop_id = ? AND status IN ('BOOKED','COMPLETED')
            """,
            (shop_id,),
        )
        recovered_revenue = _money(revenue_row["total"] if revenue_row else 0)

        recent_events = core.db_fetchall(
            conn,
            """
            SELECT e.*
            FROM events e
            WHERE e.event_type IN (
                'offer.delivery',
                'booking.customer_notified',
                'recovery.started',
                'offer.claimed',
                'booking.created'
            )
            AND (
                e.entity_id IN (
                    SELECT id FROM openings WHERE shop_id = ?
                )
                OR e.entity_id IN (
                    SELECT ofr.id
                    FROM offers ofr
                    JOIN openings o ON o.id = ofr.opening_id
                    WHERE o.shop_id = ?
                )
                OR e.entity_id IN (
                    SELECT b.id
                    FROM bookings b
                    JOIN openings o ON o.id = b.opening_id
                    WHERE o.shop_id = ?
                )
            )
            ORDER BY e.created_at DESC
            LIMIT 30
            """,
            (shop_id, shop_id, shop_id),
        )
    finally:
        conn.close()

    delivery_events = []
    for row in recent_events:
        if row["event_type"] not in ("offer.delivery", "booking.customer_notified"):
            continue
        metadata = _parse_metadata(row["metadata"])
        delivery_events.append(
            {
                "event_type": row["event_type"],
                "entity_id": row["entity_id"],
                "created_at": row["created_at"],
                "sms": bool(metadata.get("sms")),
                "email": bool(metadata.get("email")),
                "sms_live": bool(metadata.get("sms_live")),
                "email_live": bool(metadata.get("email_live")),
            }
        )

    successful_deliveries = sum(
        1 for item in delivery_events if item["sms"] or item["email"]
    )
    failed_deliveries = sum(
        1 for item in delivery_events if not item["sms"] and not item["email"]
    )

    email_configured = bool(core.RESEND_API_KEY)
    sms_configured = all(
        [
            core.TWILIO_ACCOUNT_SID,
            core.TWILIO_AUTH_TOKEN,
            core.TWILIO_FROM_NUMBER,
        ]
    )
    live_delivery_available = bool(
        (notifications.EMAIL_LIVE and email_configured)
        or (notifications.SMS_LIVE and sms_configured)
    )

    checks = [
        {
            "key": "shop",
            "label": "Studio configured",
            "ok": bool(shop and shop["name"]),
            "detail": shop["name"] if shop else "No studio record",
            "required": True,
        },
        {
            "key": "artists",
            "label": "At least one active artist",
            "ok": artists > 0,
            "detail": f"{artists} active artist{'s' if artists != 1 else ''}",
            "required": True,
        },
        {
            "key": "customers",
            "label": "Pilot customer list loaded",
            "ok": customers > 0,
            "detail": f"{customers} customers, {consented_customers} consented",
            "required": True,
        },
        {
            "key": "delivery",
            "label": "Live notification channel",
            "ok": live_delivery_available,
            "detail": (
                f"Email {'LIVE' if notifications.EMAIL_LIVE else 'demo'} / "
                f"SMS {'LIVE' if notifications.SMS_LIVE else 'demo'}"
            ),
            "required": True,
        },
        {
            "key": "base_url",
            "label": "Public HTTPS URL",
            "ok": core.PUBLIC_BASE_URL.lower().startswith("https://"),
            "detail": core.PUBLIC_BASE_URL,
            "required": True,
        },
        {
            "key": "session_secret",
            "label": "Production session secret",
            "ok": core.SESSION_SECRET != "change-me-in-production",
            "detail": "Custom secret configured" if core.SESSION_SECRET != "change-me-in-production" else "Default secret still in use",
            "required": True,
        },
        {
            "key": "database",
            "label": "Persistent production database",
            "ok": bool(core.USE_POSTGRES),
            "detail": "PostgreSQL" if core.USE_POSTGRES else "SQLite",
            "required": True,
        },
        {
            "key": "email_audience",
            "label": "Email-reachable consented customers",
            "ok": email_customers > 0 or notifications.SMS_LIVE,
            "detail": f"{email_customers} email / {phone_customers} phone",
            "required": False,
        },
    ]

    required_checks = [item for item in checks if item["required"]]
    required_passed = sum(1 for item in required_checks if item["ok"])
    readiness_percent = round(
        (required_passed / len(required_checks) * 100) if required_checks else 0
    )

    recovery_rate = round((recovered / openings * 100), 1) if openings else 0.0
    offer_conversion_rate = round((claimed_offers / offers * 100), 1) if offers else 0.0

    return {
        "version": PILOT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready": all(item["ok"] for item in required_checks),
        "readiness_percent": readiness_percent,
        "checks": checks,
        "metrics": {
            "artists": artists,
            "customers": customers,
            "consented_customers": consented_customers,
            "openings": openings,
            "recovered_openings": recovered,
            "recovery_rate": recovery_rate,
            "offers": offers,
            "claimed_offers": claimed_offers,
            "offer_conversion_rate": offer_conversion_rate,
            "recovered_revenue": recovered_revenue,
            "successful_delivery_events": successful_deliveries,
            "failed_delivery_events": failed_deliveries,
        },
        "channels": {
            "email_live": notifications.EMAIL_LIVE,
            "email_configured": email_configured,
            "sms_live": notifications.SMS_LIVE,
            "sms_configured": sms_configured,
        },
        "recent_deliveries": delivery_events[:12],
    }


@core.app.get("/healthz", response_class=JSONResponse)
def healthz():
    return {
        "status": "ok",
        "service": "empty-chair",
        "version": PILOT_VERSION,
        "database": "postgresql" if core.USE_POSTGRES else "sqlite",
    }


@core.app.get("/api/pilot/status", response_class=JSONResponse)
def pilot_status_api(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return _shop_snapshot(user["shop_id"])


@core.app.get("/pilot", response_class=HTMLResponse)
def pilot_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        shop = core.db_fetchone(
            conn,
            "SELECT * FROM shops WHERE id = ? LIMIT 1",
            (user["shop_id"],),
        )
    finally:
        conn.close()

    snapshot = _shop_snapshot(user["shop_id"])
    return core.templates.TemplateResponse(
        request=request,
        name="pilot.html",
        context={
            "user": user,
            "shop": shop,
            "pilot": snapshot,
        },
    )


# Make FastAPI's public metadata match the pilot build without touching the
# large core module.
core.app.version = PILOT_VERSION
