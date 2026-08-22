"""Guided onboarding wizard for Empty Chair shop owners and demos."""

import uuid

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core
import enrichment_v1


app = core.app


def _count(conn, query, params=()):
    row = core.db_fetchone(conn, query, params)
    if not row:
        return 0
    try:
        return int(row["n"] or 0)
    except (KeyError, TypeError):
        return int(row[0] or 0)


def _snapshot(shop_id, user_id=None):
    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT * FROM shops WHERE id = ? LIMIT 1", (shop_id,))
        artists = _count(conn, "SELECT COUNT(*) AS n FROM artists WHERE shop_id = ?", (shop_id,))
        customers = _count(conn, "SELECT COUNT(*) AS n FROM customers WHERE shop_id = ?", (shop_id,))
        consented = _count(conn, "SELECT COUNT(*) AS n FROM customers WHERE shop_id = ? AND communication_consent = 1", (shop_id,))
        calendar_ready = False
        if user_id:
            calendar_ready = bool(core.db_fetchone(conn, "SELECT user_id FROM google_calendar_connections WHERE user_id = ? LIMIT 1", (user_id,)))
        try:
            enrichment_v1.ensure_schema(conn)
            location = core.db_fetchone(conn, "SELECT address_text,latitude,longitude FROM enrichment_locations WHERE shop_id=? AND entity_type='shop' AND entity_id=?", (shop_id, shop_id))
        except Exception:
            location = None
    finally:
        conn.close()

    return {
        "shop": shop,
        "artists": artists,
        "customers": customers,
        "consented": consented,
        "shop_ready": bool(shop and shop["name"]),
        "shop_location": location,
        "location_ready": bool(location and location["latitude"] is not None and location["longitude"] is not None),
        "artist_ready": artists > 0,
        "customers_ready": customers > 0,
        "calendar_ready": calendar_ready,
        "stripe_connected": bool(shop and shop["stripe_account_id"]),
        "stripe_ready": bool(shop and shop["stripe_charges_enabled"] and shop["stripe_payouts_enabled"]),
        "ready": artists > 0 and customers > 0,
    }


def needs_onboarding(shop_id):
    state = _snapshot(shop_id)
    return not state["ready"]


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, step: int = 1):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    state = _snapshot(user["shop_id"], user["id"])
    step = max(1, min(int(step or 1), 6))

    return core.templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={"user": user, "shop": state["shop"], "state": state, "step": step, "demo_mode": core.DEMO_MODE},
    )


@app.post("/setup/shop")
def setup_shop(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        core.db_execute(conn, "UPDATE shops SET name = ?, email = ?, phone = ? WHERE id = ?", (name.strip(), email.strip() or None, phone.strip() or None, user["shop_id"]))
        conn.commit()
    finally:
        conn.close()

    if address.strip():
        try:
            enrichment_v1.set_shop_location(user["shop_id"], address.strip(), source="shop_setup")
        except Exception as exc:
            core.event("enrichment.shop_failed", "shop", user["shop_id"], str(exc))

    return RedirectResponse("/setup?step=2", status_code=303)


@app.post("/setup/artist")
def setup_artist(
    request: Request,
    name: str = Form(...),
    styles: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        core.db_execute(conn, """INSERT INTO artists(id, shop_id, name, email, phone, styles, services, active) VALUES (?, ?, ?, ?, ?, ?, 'tattoo', 1)""", (f"artist_{uuid.uuid4().hex[:12]}", user["shop_id"], name.strip(), email.strip() or None, phone.strip() or None, styles.strip()))
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/setup?step=3", status_code=303)


@app.post("/setup/demo")
def setup_demo(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    if not core.DEMO_MODE:
        return RedirectResponse("/setup", status_code=303)

    conn = core.connect()
    try:
        artist = core.db_fetchone(conn, "SELECT id FROM artists WHERE shop_id = ? ORDER BY name LIMIT 1", (user["shop_id"],))
        if not artist:
            artist_id = f"artist_{uuid.uuid4().hex[:12]}"
            core.db_execute(conn, """INSERT INTO artists(id, shop_id, name, email, phone, styles, services, active) VALUES (?, ?, 'Alex Rivera', NULL, NULL, 'Traditional, Blackwork', 'tattoo', 1)""", (artist_id, user["shop_id"]))
        else:
            artist_id = artist["id"]

        existing = _count(conn, "SELECT COUNT(*) AS n FROM customers WHERE shop_id = ?", (user["shop_id"],))
        if existing == 0:
            samples = [
                ("Sarah Miller", "+17065550101", "sarah@example.com", "Traditional", 325),
                ("Mike Carter", "+17065550102", "mike@example.com", "Blackwork", 400),
                ("Jessica Lee", "+17065550103", "jessica@example.com", "Traditional", 275),
                ("Taylor Reed", "+17065550104", "taylor@example.com", "Blackwork", 350),
                ("Morgan Hayes", "+17065550105", "morgan@example.com", "Traditional", 300),
            ]
            for customer_name, phone, email, style, spend in samples:
                core.db_execute(conn, """INSERT INTO customers(id, shop_id, name, phone, email, communication_consent, preferred_artists, preferred_styles, preferred_services, appointment_count, completed_count, cancellation_count, no_show_count, average_spend, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, 'tattoo', 3, 2, 0, 0, ?, ?, ?)""", (f"customer_{uuid.uuid4().hex[:12]}", user["shop_id"], customer_name, phone, email, "Alex Rivera", style, spend, core.now_iso(), core.now_iso()))
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/setup?step=4", status_code=303)
