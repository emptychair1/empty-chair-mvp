"""Reusable, isolated live-demo account and reset controls."""

import os
from datetime import date, timedelta

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core


app = core.app
DEMO_ENABLED = os.getenv("EMPTY_CHAIR_PUBLIC_DEMO", "false").lower() == "true"
DEMO_USER_ID = "user_live_demo"
DEMO_SHOP_ID = "shop_live_demo"
DEMO_EMAIL = os.getenv("EMPTY_CHAIR_DEMO_EMAIL", "demo@emptychair.app")
DEMO_PASSWORD = os.getenv("EMPTY_CHAIR_DEMO_PASSWORD", "EmptyChairDemo!")

# A demo claim must never trigger live SMS or email, even when the production
# account has delivery credentials configured.
_live_send_recovery_email = core.send_recovery_email


def _demo_safe_send_recovery_email(opening_id):
    if str(opening_id).startswith("demo_"):
        core.event("demo.delivery_suppressed", "opening", opening_id)
        return None
    return _live_send_recovery_email(opening_id)


core.send_recovery_email = _demo_safe_send_recovery_email


def _require_enabled():
    if not DEMO_ENABLED:
        raise HTTPException(404, "Demo account is not enabled.")


def _ensure_account():
    password_hash, password_salt = core.hash_password(DEMO_PASSWORD)
    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT id FROM shops WHERE id=?", (DEMO_SHOP_ID,))
        if not shop:
            core.db_execute(
                conn,
                "INSERT INTO shops(id,name,timezone,email,status,created_at) VALUES (?,?,?,?,?,?)",
                (DEMO_SHOP_ID, "Black Lantern Tattoo", "America/New_York", DEMO_EMAIL, "active", core.now_iso()),
            )
        user = core.db_fetchone(conn, "SELECT id FROM users WHERE id=?", (DEMO_USER_ID,))
        if not user:
            core.db_execute(
                conn,
                "INSERT INTO users(id,shop_id,name,email,password_hash,password_salt,is_active,created_at) VALUES (?,?,?,?,?,?,1,?)",
                (DEMO_USER_ID, DEMO_SHOP_ID, "Demo Owner", DEMO_EMAIL, password_hash, password_salt, core.now_iso()),
            )
        conn.commit()
    finally:
        conn.close()


def _reset_data():
    """Reset only the isolated demo shop; never touch real shop records."""
    _ensure_account()
    conn = core.connect()
    try:
        opening_ids = [row["id"] for row in core.db_fetchall(conn, "SELECT id FROM openings WHERE shop_id=?", (DEMO_SHOP_ID,))]
        artist_ids = [row["id"] for row in core.db_fetchall(conn, "SELECT id FROM artists WHERE shop_id=?", (DEMO_SHOP_ID,))]
        if opening_ids:
            marks = ",".join("?" for _ in opening_ids)
            core.db_execute(conn, f"DELETE FROM google_booking_events WHERE booking_id IN (SELECT id FROM bookings WHERE opening_id IN ({marks}))", opening_ids)
            core.db_execute(conn, f"DELETE FROM bookings WHERE opening_id IN ({marks})", opening_ids)
            core.db_execute(conn, f"DELETE FROM offers WHERE opening_id IN ({marks})", opening_ids)
        core.db_execute(conn, "DELETE FROM autopilot_campaign_openings WHERE campaign_id IN (SELECT id FROM autopilot_campaigns WHERE shop_id=?)", (DEMO_SHOP_ID,))
        core.db_execute(conn, "DELETE FROM autopilot_campaigns WHERE shop_id=?", (DEMO_SHOP_ID,))
        core.db_execute(conn, "DELETE FROM openings WHERE shop_id=?", (DEMO_SHOP_ID,))
        core.db_execute(conn, "DELETE FROM customers WHERE shop_id=?", (DEMO_SHOP_ID,))
        if artist_ids:
            marks = ",".join("?" for _ in artist_ids)
            core.db_execute(conn, f"DELETE FROM artist_calendar_connections WHERE artist_id IN ({marks})", artist_ids)
        core.db_execute(conn, "DELETE FROM artists WHERE shop_id=?", (DEMO_SHOP_ID,))
        core.db_execute(conn, "DELETE FROM events WHERE entity_id LIKE 'demo_%'")

        today = date.today()
        claim_day = today + timedelta(days=2)
        open_day = today + timedelta(days=4)
        completed_day = today - timedelta(days=3)
        now = core.now_iso()
        core.db_execute(conn, "INSERT INTO artists(id,shop_id,name,email,phone,styles,services,active) VALUES (?,?,?,?,?,?,?,1)",
                        ("demo_artist_alex", DEMO_SHOP_ID, "Alex Rivera", "alex@example.test", "+17065550101", "Blackwork, Traditional", "Tattoo"))
        core.db_execute(conn, "INSERT INTO artists(id,shop_id,name,email,phone,styles,services,active) VALUES (?,?,?,?,?,?,?,1)",
                        ("demo_artist_morgan", DEMO_SHOP_ID, "Morgan Vale", "morgan@example.test", "+17065550102", "Fine line, Realism", "Tattoo"))
        customers = [
            ("demo_customer_jordan", "Jordan Lee", None, None, "demo_artist_alex", "Blackwork", 425),
            ("demo_customer_casey", "Casey Reed", None, None, "demo_artist_alex", "Traditional", 350),
            ("demo_customer_riley", "Riley Chen", None, None, "demo_artist_morgan", "Fine line", 300),
        ]
        for cid, name, phone, email, artist, style, spend in customers:
            core.db_execute(conn, "INSERT INTO customers(id,shop_id,name,phone,email,communication_consent,preferred_artists,preferred_styles,preferred_services,appointment_count,completed_count,cancellation_count,no_show_count,average_spend,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?,3,3,0,0,?,?,?)",
                            (cid, DEMO_SHOP_ID, name, phone, email, artist, style, "Tattoo", spend, now, now))
        openings = [
            ("demo_opening_claim", "demo_artist_alex", claim_day.isoformat(), "14:00", "17:00", "Blackwork", 450, "RECOVERY_ACTIVE"),
            ("demo_opening_open", "demo_artist_morgan", open_day.isoformat(), "12:00", "15:00", "Fine line", 350, "OPEN"),
            ("demo_opening_done", "demo_artist_alex", completed_day.isoformat(), "13:00", "16:00", "Traditional", 500, "COMPLETED"),
        ]
        for oid, aid, day, start, end, style, price, status in openings:
            core.db_execute(conn, "INSERT INTO openings(id,shop_id,artist_id,date,start_time,end_time,service,style,price,status,created_at,expires_at) VALUES (?,?,?,?,? ,?,'Tattoo',?,?,?,?,?)",
                            (oid, DEMO_SHOP_ID, aid, day, start, end, style, price, status, now, (today + timedelta(days=7)).isoformat() + "T23:59:00+00:00"))
        core.db_execute(conn, "INSERT INTO offers(id,opening_id,customer_id,score,rank,channel,sent_at,expires_at,status) VALUES (?,?,?,?,?,?,?,?,?)",
                        ("demo_offer_claim", "demo_opening_claim", "demo_customer_jordan", 98, 1, "email", now, (today + timedelta(days=7)).isoformat() + "T23:59:00+00:00", "SENT"))
        core.db_execute(conn, "INSERT INTO autopilot_campaigns(id,shop_id,artist_id,mode,start_date,end_date,start_time,end_time,slot_minutes,min_price,target_utilization,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("demo_campaign", DEMO_SHOP_ID, "demo_artist_alex", "custom", claim_day.isoformat(), claim_day.isoformat(), "14:00", "17:00", 180, 450, 85, "ACTIVE", now))
        core.db_execute(conn, "INSERT INTO autopilot_campaign_openings(campaign_id,opening_id) VALUES (?,?)", ("demo_campaign", "demo_opening_claim"))
        core.db_execute(conn, "INSERT INTO bookings(id,opening_id,customer_id,artist_id,status,amount,deposit_amount,deposit_status,booked_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        ("demo_booking_done", "demo_opening_done", "demo_customer_casey", "demo_artist_alex", "COMPLETED", 500, 100, "PAID", now))
        core.db_execute(conn, "UPDATE openings SET booking_id=? WHERE id=?", ("demo_booking_done", "demo_opening_done"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.get("/demo/login", response_class=HTMLResponse)
def demo_login_page(request: Request):
    _require_enabled()
    return core.templates.TemplateResponse(request=request, name="demo_login.html", context={"email": DEMO_EMAIL})


@app.post("/demo/login")
def demo_login(request: Request):
    _require_enabled()
    _reset_data()
    request.session.clear()
    request.session["user_id"] = DEMO_USER_ID
    return RedirectResponse("/demo", status_code=303)


@app.get("/demo", response_class=HTMLResponse)
def demo_control(request: Request):
    _require_enabled()
    user = core.get_current_user(request)
    if not user or user["id"] != DEMO_USER_ID:
        return RedirectResponse("/demo/login", status_code=303)
    conn = core.connect()
    try:
        offer = core.db_fetchone(conn, "SELECT status FROM offers WHERE id='demo_offer_claim'")
        booking = core.db_fetchone(conn, "SELECT id,status FROM bookings WHERE opening_id='demo_opening_claim' ORDER BY rowid DESC LIMIT 1")
    finally:
        conn.close()
    return core.templates.TemplateResponse(request=request, name="demo_control.html", context={"user": user, "offer": offer, "booking": booking})


@app.post("/demo/reset")
def demo_reset(request: Request, finish: str = Form("no")):
    _require_enabled()
    user = core.get_current_user(request)
    if not user or user["id"] != DEMO_USER_ID:
        raise HTTPException(403, "Demo account required.")
    _reset_data()
    if finish == "yes":
        request.session.clear()
        return RedirectResponse("/demo/login?reset=1", status_code=303)
    return RedirectResponse("/demo", status_code=303)
