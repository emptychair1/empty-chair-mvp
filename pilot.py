"""Pilot control center and Autopilot availability blocks for Empty Chair.

Pilot v1.1 extends the original cancellation-recovery pilot into controlled
calendar filling. A shop can define a week/month availability block, Empty Chair
creates bookable openings, and a small number of openings are activated at a
time through the existing recovery queue. Existing consent, customer ranking,
frequency protection, claim, and booking logic remain authoritative.
"""

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import app as core
import notifications


PILOT_VERSION = "1.1.0-pilot"
AUTOPILOT_ACTIVE_WINDOW = 3


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


def _ensure_autopilot_schema():
    conn = core.connect()
    try:
        core.db_execute(
            conn,
            """
            CREATE TABLE IF NOT EXISTS autopilot_campaigns (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                artist_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                slot_minutes INTEGER NOT NULL DEFAULT 120,
                min_price REAL NOT NULL DEFAULT 0,
                target_utilization INTEGER NOT NULL DEFAULT 85,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL,
                stopped_at TEXT,
                FOREIGN KEY(shop_id) REFERENCES shops(id),
                FOREIGN KEY(artist_id) REFERENCES artists(id)
            )
            """,
        )
        core.db_execute(
            conn,
            """
            CREATE TABLE IF NOT EXISTS autopilot_campaign_openings (
                campaign_id TEXT NOT NULL,
                opening_id TEXT NOT NULL UNIQUE,
                PRIMARY KEY(campaign_id, opening_id),
                FOREIGN KEY(campaign_id) REFERENCES autopilot_campaigns(id),
                FOREIGN KEY(opening_id) REFERENCES openings(id)
            )
            """,
        )
        core.db_execute(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_autopilot_shop_status
            ON autopilot_campaigns(shop_id, status)
            """,
        )
        core.db_execute(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_autopilot_opening_campaign
            ON autopilot_campaign_openings(campaign_id)
            """,
        )
        conn.commit()
    finally:
        conn.close()


def _parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_time(value):
    return datetime.strptime(value, "%H:%M").time()


def _time_to_minutes(value):
    parsed = _parse_time(value)
    return parsed.hour * 60 + parsed.minute


def _minutes_to_time(value):
    hour = value // 60
    minute = value % 60
    return f"{hour:02d}:{minute:02d}"


def _campaign_rows(shop_id):
    conn = core.connect()
    try:
        rows = core.db_fetchall(
            conn,
            """
            SELECT c.*, a.name AS artist_name
            FROM autopilot_campaigns c
            JOIN artists a ON a.id = c.artist_id
            WHERE c.shop_id = ?
            ORDER BY c.created_at DESC
            LIMIT 12
            """,
            (shop_id,),
        )

        result = []
        for row in rows:
            total = _count(
                conn,
                """
                SELECT COUNT(*) AS total
                FROM autopilot_campaign_openings
                WHERE campaign_id = ?
                """,
                (row["id"],),
            )
            filled = _count(
                conn,
                """
                SELECT COUNT(*) AS total
                FROM autopilot_campaign_openings co
                JOIN openings o ON o.id = co.opening_id
                WHERE co.campaign_id = ?
                  AND o.status IN ('BOOKED','COMPLETED','CLAIMED')
                """,
                (row["id"],),
            )
            active = _count(
                conn,
                """
                SELECT COUNT(*) AS total
                FROM autopilot_campaign_openings co
                JOIN openings o ON o.id = co.opening_id
                WHERE co.campaign_id = ?
                  AND o.status = 'RECOVERY_ACTIVE'
                """,
                (row["id"],),
            )
            remaining = _count(
                conn,
                """
                SELECT COUNT(*) AS total
                FROM autopilot_campaign_openings co
                JOIN openings o ON o.id = co.opening_id
                WHERE co.campaign_id = ?
                  AND o.status IN ('OPEN','RECOVERY_ACTIVE','NO_RECOVERY')
                """,
                (row["id"],),
            )
            utilization = round((filled / total * 100), 1) if total else 0.0
            result.append(
                {
                    "id": row["id"],
                    "artist_id": row["artist_id"],
                    "artist_name": row["artist_name"],
                    "mode": row["mode"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "start_time": row["start_time"],
                    "end_time": row["end_time"],
                    "slot_minutes": row["slot_minutes"],
                    "min_price": _money(row["min_price"]),
                    "target_utilization": int(row["target_utilization"] or 85),
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "total_slots": total,
                    "filled_slots": filled,
                    "active_slots": active,
                    "remaining_slots": remaining,
                    "utilization": utilization,
                }
            )
        return result
    finally:
        conn.close()


def _create_campaign_openings(campaign_id):
    conn = core.connect()
    try:
        campaign = core.db_fetchone(
            conn,
            "SELECT * FROM autopilot_campaigns WHERE id = ? LIMIT 1",
            (campaign_id,),
        )
        if not campaign:
            return 0

        cursor_date = _parse_date(campaign["start_date"])
        end_date = _parse_date(campaign["end_date"])
        start_minutes = _time_to_minutes(campaign["start_time"])
        end_minutes = _time_to_minutes(campaign["end_time"])
        slot_minutes = max(30, int(campaign["slot_minutes"] or 120))
        created = 0

        while cursor_date <= end_date:
            # Tattoo shops often work weekends, so every selected calendar day
            # is valid. The owner controls the exact date range.
            minute = start_minutes
            while minute + slot_minutes <= end_minutes:
                opening_id = f"open_{uuid.uuid4().hex[:12]}"
                start_label = _minutes_to_time(minute)
                end_label = _minutes_to_time(minute + slot_minutes)
                timestamp = core.now_iso()
                expires_at = datetime.combine(
                    cursor_date,
                    _parse_time(start_label),
                    tzinfo=timezone.utc,
                ) + timedelta(hours=24)

                core.db_execute(
                    conn,
                    """
                    INSERT INTO openings(
                        id, shop_id, artist_id, date, start_time, end_time,
                        service, style, price, status, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
                    """,
                    (
                        opening_id,
                        campaign["shop_id"],
                        campaign["artist_id"],
                        cursor_date.isoformat(),
                        start_label,
                        end_label,
                        "tattoo",
                        None,
                        float(campaign["min_price"] or 0),
                        timestamp,
                        expires_at.isoformat(),
                    ),
                )
                core.db_execute(
                    conn,
                    """
                    INSERT INTO autopilot_campaign_openings(campaign_id, opening_id)
                    VALUES (?, ?)
                    """,
                    (campaign_id, opening_id),
                )
                created += 1
                minute += slot_minutes
            cursor_date += timedelta(days=1)

        conn.commit()
        return created
    finally:
        conn.close()


def _autopilot_tick(shop_id):
    """Keep only a small controlled set of campaign slots actively offering."""
    campaigns = _campaign_rows(shop_id)
    activated = 0

    for campaign in campaigns:
        if campaign["status"] != "ACTIVE":
            continue

        if campaign["utilization"] >= campaign["target_utilization"]:
            conn = core.connect()
            try:
                core.db_execute(
                    conn,
                    """
                    UPDATE autopilot_campaigns
                    SET status = 'TARGET_REACHED', stopped_at = ?
                    WHERE id = ? AND status = 'ACTIVE'
                    """,
                    (core.now_iso(), campaign["id"]),
                )
                conn.commit()
            finally:
                conn.close()
            core.event(
                "autopilot.target_reached",
                "autopilot_campaign",
                campaign["id"],
                json.dumps({"utilization": campaign["utilization"]}),
            )
            continue

        capacity = max(0, AUTOPILOT_ACTIVE_WINDOW - campaign["active_slots"])
        if capacity <= 0:
            continue

        conn = core.connect()
        try:
            candidates = core.db_fetchall(
                conn,
                """
                SELECT o.id
                FROM autopilot_campaign_openings co
                JOIN openings o ON o.id = co.opening_id
                WHERE co.campaign_id = ?
                  AND o.status IN ('OPEN','NO_RECOVERY')
                ORDER BY o.date, o.start_time
                LIMIT ?
                """,
                (campaign["id"], capacity),
            )
        finally:
            conn.close()

        for candidate in candidates:
            try:
                offer_id = core.start_recovery_campaign(candidate["id"])
                if offer_id:
                    activated += 1
                    core.event(
                        "autopilot.slot_activated",
                        "opening",
                        candidate["id"],
                        json.dumps({"campaign_id": campaign["id"]}),
                    )
            except Exception as exc:
                core.event(
                    "autopilot.activation_failed",
                    "opening",
                    candidate["id"],
                    json.dumps({"campaign_id": campaign["id"], "error": str(exc)}),
                )

    return activated


def _shop_snapshot(shop_id):
    _autopilot_tick(shop_id)

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
            "SELECT COUNT(*) AS total FROM customers WHERE shop_id = ? AND communication_consent = 1",
            (shop_id,),
        )
        email_customers = _count(
            conn,
            """
            SELECT COUNT(*) AS total FROM customers
            WHERE shop_id = ? AND communication_consent = 1
              AND email IS NOT NULL AND TRIM(email) <> ''
            """,
            (shop_id,),
        )
        phone_customers = _count(
            conn,
            """
            SELECT COUNT(*) AS total FROM customers
            WHERE shop_id = ? AND communication_consent = 1
              AND phone IS NOT NULL AND TRIM(phone) <> ''
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
            SELECT COUNT(*) AS total FROM openings
            WHERE shop_id = ? AND status IN ('BOOKED','COMPLETED')
            """,
            (shop_id,),
        )
        offers = _count(
            conn,
            """
            SELECT COUNT(*) AS total FROM offers ofr
            JOIN openings o ON o.id = ofr.opening_id WHERE o.shop_id = ?
            """,
            (shop_id,),
        )
        claimed_offers = _count(
            conn,
            """
            SELECT COUNT(*) AS total FROM offers ofr
            JOIN openings o ON o.id = ofr.opening_id
            WHERE o.shop_id = ? AND ofr.status = 'CLAIMED'
            """,
            (shop_id,),
        )
        revenue_row = core.db_fetchone(
            conn,
            """
            SELECT COALESCE(SUM(price), 0) AS total FROM openings
            WHERE shop_id = ? AND status IN ('BOOKED','COMPLETED')
            """,
            (shop_id,),
        )
        recovered_revenue = _money(revenue_row["total"] if revenue_row else 0)

        recent_events = core.db_fetchall(
            conn,
            """
            SELECT e.* FROM events e
            WHERE e.event_type IN (
                'offer.delivery','booking.customer_notified','recovery.started',
                'offer.claimed','booking.created','autopilot.slot_activated',
                'autopilot.target_reached','autopilot.activation_failed'
            )
            ORDER BY e.created_at DESC LIMIT 40
            """,
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

    successful_deliveries = sum(1 for item in delivery_events if item["sms"] or item["email"])
    failed_deliveries = sum(1 for item in delivery_events if not item["sms"] and not item["email"])
    email_configured = bool(core.RESEND_API_KEY)
    sms_configured = all([core.TWILIO_ACCOUNT_SID, core.TWILIO_AUTH_TOKEN, core.TWILIO_FROM_NUMBER])
    live_delivery_available = bool(
        (notifications.EMAIL_LIVE and email_configured)
        or (notifications.SMS_LIVE and sms_configured)
    )

    checks = [
        {"key": "shop", "label": "Studio configured", "ok": bool(shop and shop["name"]), "detail": shop["name"] if shop else "No studio record", "required": True},
        {"key": "artists", "label": "At least one active artist", "ok": artists > 0, "detail": f"{artists} active artist{'s' if artists != 1 else ''}", "required": True},
        {"key": "customers", "label": "Pilot customer list loaded", "ok": customers > 0, "detail": f"{customers} customers, {consented_customers} consented", "required": True},
        {"key": "delivery", "label": "Live notification channel", "ok": live_delivery_available, "detail": f"Email {'LIVE' if notifications.EMAIL_LIVE else 'demo'} / SMS {'LIVE' if notifications.SMS_LIVE else 'demo'}", "required": True},
        {"key": "base_url", "label": "Public HTTPS URL", "ok": core.PUBLIC_BASE_URL.lower().startswith("https://"), "detail": core.PUBLIC_BASE_URL, "required": True},
        {"key": "session_secret", "label": "Production session secret", "ok": core.SESSION_SECRET != "change-me-in-production", "detail": "Custom secret configured" if core.SESSION_SECRET != "change-me-in-production" else "Default secret still in use", "required": True},
        {"key": "database", "label": "Persistent production database", "ok": bool(core.USE_POSTGRES), "detail": "PostgreSQL" if core.USE_POSTGRES else "SQLite", "required": True},
        {"key": "email_audience", "label": "Email-reachable consented customers", "ok": email_customers > 0 or notifications.SMS_LIVE, "detail": f"{email_customers} email / {phone_customers} phone", "required": False},
    ]

    required_checks = [item for item in checks if item["required"]]
    required_passed = sum(1 for item in required_checks if item["ok"])
    readiness_percent = round((required_passed / len(required_checks) * 100) if required_checks else 0)
    recovery_rate = round((recovered / openings * 100), 1) if openings else 0.0
    offer_conversion_rate = round((claimed_offers / offers * 100), 1) if offers else 0.0
    campaigns = _campaign_rows(shop_id)

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
            "active_autopilot_campaigns": sum(1 for item in campaigns if item["status"] == "ACTIVE"),
        },
        "channels": {
            "email_live": notifications.EMAIL_LIVE,
            "email_configured": email_configured,
            "sms_live": notifications.SMS_LIVE,
            "sms_configured": sms_configured,
        },
        "campaigns": campaigns,
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


@core.app.post("/pilot/autopilot")
def create_autopilot_campaign(
    request: Request,
    artist_id: str = Form(...),
    mode: str = Form("week"),
    start_date: str = Form(...),
    end_date: str = Form(...),
    start_time: str = Form("12:00"),
    end_time: str = Form("20:00"),
    slot_minutes: int = Form(120),
    min_price: float = Form(250),
    target_utilization: int = Form(85),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    mode = mode.lower().strip()
    if mode not in {"week", "month", "custom"}:
        mode = "custom"

    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if end < start:
        return RedirectResponse("/pilot?error=End+date+must+be+after+start+date", status_code=303)
    if (end - start).days > 31:
        return RedirectResponse("/pilot?error=Pilot+campaigns+are+limited+to+31+days", status_code=303)
    if _time_to_minutes(end_time) <= _time_to_minutes(start_time):
        return RedirectResponse("/pilot?error=End+time+must+be+after+start+time", status_code=303)

    slot_minutes = min(max(int(slot_minutes), 30), 480)
    target_utilization = min(max(int(target_utilization), 10), 100)
    min_price = max(float(min_price), 0)

    conn = core.connect()
    try:
        artist = core.db_fetchone(
            conn,
            "SELECT id FROM artists WHERE id = ? AND shop_id = ? AND active = 1 LIMIT 1",
            (artist_id, user["shop_id"]),
        )
        if not artist:
            return RedirectResponse("/pilot?error=Choose+a+valid+active+artist", status_code=303)

        campaign_id = f"auto_{uuid.uuid4().hex[:12]}"
        core.db_execute(
            conn,
            """
            INSERT INTO autopilot_campaigns(
                id, shop_id, artist_id, mode, start_date, end_date,
                start_time, end_time, slot_minutes, min_price,
                target_utilization, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (
                campaign_id,
                user["shop_id"],
                artist_id,
                mode,
                start_date,
                end_date,
                start_time,
                end_time,
                slot_minutes,
                min_price,
                target_utilization,
                core.now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    created = _create_campaign_openings(campaign_id)
    core.event(
        "autopilot.started",
        "autopilot_campaign",
        campaign_id,
        json.dumps({"slots_created": created, "mode": mode}),
    )
    _autopilot_tick(user["shop_id"])
    return RedirectResponse(f"/pilot?started={created}", status_code=303)


@core.app.post("/pilot/autopilot/{campaign_id}/stop")
def stop_autopilot_campaign(request: Request, campaign_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        campaign = core.db_fetchone(
            conn,
            "SELECT id FROM autopilot_campaigns WHERE id = ? AND shop_id = ? LIMIT 1",
            (campaign_id, user["shop_id"]),
        )
        if campaign:
            core.db_execute(
                conn,
                """
                UPDATE autopilot_campaigns
                SET status = 'STOPPED', stopped_at = ?
                WHERE id = ?
                """,
                (core.now_iso(), campaign_id),
            )
            conn.commit()
    finally:
        conn.close()

    if campaign:
        core.event("autopilot.stopped", "autopilot_campaign", campaign_id)
    return RedirectResponse("/pilot", status_code=303)


@core.app.get("/pilot", response_class=HTMLResponse)
def pilot_page(request: Request, started: int = 0, error: str = ""):
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
        artists = core.db_fetchall(
            conn,
            "SELECT * FROM artists WHERE shop_id = ? AND active = 1 ORDER BY name",
            (user["shop_id"],),
        )
    finally:
        conn.close()

    snapshot = _shop_snapshot(user["shop_id"])
    today = date.today()
    week_end = today + timedelta(days=6)
    month_end = min(today + timedelta(days=30), date(today.year + (today.month == 12), 1 if today.month == 12 else today.month + 1, 1) - timedelta(days=1))

    return core.templates.TemplateResponse(
        request=request,
        name="pilot.html",
        context={
            "user": user,
            "shop": shop,
            "artists": artists,
            "pilot": snapshot,
            "started": started,
            "error": error,
            "today": today.isoformat(),
            "week_end": week_end.isoformat(),
            "month_end": month_end.isoformat(),
        },
    )


_ensure_autopilot_schema()
core.app.version = PILOT_VERSION
