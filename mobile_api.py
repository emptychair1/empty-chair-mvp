from typing import Any

from fastapi import Body, HTTPException, Request

import app as core

app = core.app


def as_dict(row):
    return dict(row) if row is not None else None


def require_api_user(request: Request):
    user = core.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def opening_payload(row):
    data = as_dict(row)
    if not data:
        return None
    data["price"] = float(data.get("price") or 0)
    return data


@app.post("/api/auth/login")
def api_login(request: Request, payload: dict[str, Any] = Body(...)):
    email = core.normalize_email(payload.get("email", ""))
    password = str(payload.get("password", ""))
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    conn = core.connect()
    user = core.db_fetchone(
        conn,
        """
        SELECT u.*, s.name AS shop_name, s.timezone AS shop_timezone,
               s.email AS shop_email, s.phone AS shop_phone,
               s.booking_url AS shop_booking_url
        FROM users u
        JOIN shops s ON s.id = u.shop_id
        WHERE u.email = ? AND u.is_active = 1
        LIMIT 1
        """,
        (email,),
    )
    conn.close()

    if not user or not core.verify_password(password, user["password_hash"], user["password_salt"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    request.session.clear()
    request.session["user_id"] = user["id"]
    return {"user": {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "shop_id": user["shop_id"],
        "shop_name": user["shop_name"],
        "shop_timezone": user["shop_timezone"],
    }}


@app.post("/api/auth/logout")
def api_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def api_me(request: Request):
    user = require_api_user(request)
    return {"user": {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "shop_id": user["shop_id"],
        "shop_name": user["shop_name"],
        "shop_timezone": user["shop_timezone"],
    }}


@app.get("/api/dashboard")
def api_dashboard(request: Request):
    user = require_api_user(request)
    conn = core.connect()
    openings = core.db_fetchall(conn, """
        SELECT o.*, a.name AS artist_name
        FROM openings o JOIN artists a ON a.id = o.artist_id
        WHERE o.shop_id = ? ORDER BY o.date DESC, o.start_time DESC
    """, (user["shop_id"],))
    customers = core.db_fetchone(conn, "SELECT COUNT(*) AS count FROM customers WHERE shop_id = ?", (user["shop_id"],))
    bookings = core.db_fetchall(conn, """
        SELECT b.*, o.shop_id FROM bookings b
        JOIN openings o ON o.id = b.opening_id
        WHERE o.shop_id = ?
    """, (user["shop_id"],))
    conn.close()

    recovered = sum(float(b["amount"] or 0) for b in bookings if b["status"] in {"BOOKED", "COMPLETED", "CONFIRMED", "PENDING"})
    recovered_count = sum(1 for b in bookings if b["status"] in {"BOOKED", "COMPLETED", "CONFIRMED", "PENDING"})
    at_risk = sum(float(o["price"] or 0) for o in openings if o["status"] in {"OPEN", "RECOVERY_ACTIVE"})
    active = sum(1 for o in openings if o["status"] == "RECOVERY_ACTIVE")

    return {
        "metrics": {
            "total_openings": len(openings),
            "recovered_revenue": recovered,
            "recovered_bookings": recovered_count,
            "customers": int(customers["count"] if customers else 0),
            "money_at_risk": at_risk,
            "active_recoveries": active,
        },
        "openings": [opening_payload(o) for o in openings],
    }


@app.get("/api/openings")
def api_openings(request: Request):
    user = require_api_user(request)
    conn = core.connect()
    rows = core.db_fetchall(conn, """
        SELECT o.*, a.name AS artist_name
        FROM openings o JOIN artists a ON a.id = o.artist_id
        WHERE o.shop_id = ? ORDER BY o.date DESC, o.start_time DESC
    """, (user["shop_id"],))
    conn.close()
    return {"openings": [opening_payload(row) for row in rows]}


@app.get("/api/openings/{opening_id}")
def api_opening(request: Request, opening_id: str):
    user = require_api_user(request)
    conn = core.connect()
    opening = core.db_fetchone(conn, """
        SELECT o.*, a.name AS artist_name
        FROM openings o JOIN artists a ON a.id = o.artist_id
        WHERE o.id = ? AND o.shop_id = ? LIMIT 1
    """, (opening_id, user["shop_id"]))
    if not opening:
        conn.close()
        raise HTTPException(status_code=404, detail="Opening not found")
    offers = core.db_fetchall(conn, """
        SELECT ofr.*, c.name AS customer_name, c.phone AS customer_phone
        FROM offers ofr JOIN customers c ON c.id = ofr.customer_id
        WHERE ofr.opening_id = ? ORDER BY ofr.rank
    """, (opening_id,))
    conn.close()
    return {"opening": opening_payload(opening), "offers": [as_dict(o) for o in offers]}


@app.get("/api/recovery")
def api_recovery(request: Request):
    user = require_api_user(request)
    conn = core.connect()
    openings = core.db_fetchall(conn, """
        SELECT o.*, a.name AS artist_name
        FROM openings o JOIN artists a ON a.id = o.artist_id
        WHERE o.shop_id = ? AND o.status IN ('RECOVERY_ACTIVE','CLAIMED','BOOKED','COMPLETED','NO_RECOVERY')
        ORDER BY o.created_at DESC
    """, (user["shop_id"],))
    campaigns = []
    for opening in openings:
        offers = core.db_fetchall(conn, """
            SELECT ofr.*, c.name AS customer_name, c.phone AS customer_phone
            FROM offers ofr JOIN customers c ON c.id = ofr.customer_id
            WHERE ofr.opening_id = ? ORDER BY ofr.rank
        """, (opening["id"],))
        campaigns.append({"opening": opening_payload(opening), "offers": [as_dict(o) for o in offers]})
    conn.close()
    return {"campaigns": campaigns}


@app.get("/api/customers")
def api_customers(request: Request):
    user = require_api_user(request)
    conn = core.connect()
    rows = core.db_fetchall(conn, "SELECT * FROM customers WHERE shop_id = ? ORDER BY completed_count DESC, name", (user["shop_id"],))
    conn.close()
    return {"customers": [as_dict(row) for row in rows]}


@app.get("/api/artists")
def api_artists(request: Request):
    user = require_api_user(request)
    conn = core.connect()
    rows = core.db_fetchall(conn, "SELECT * FROM artists WHERE shop_id = ? AND active = 1 ORDER BY name", (user["shop_id"],))
    conn.close()
    return {"artists": [as_dict(row) for row in rows]}


@app.get("/api/bookings")
def api_bookings(request: Request):
    user = require_api_user(request)
    conn = core.connect()
    rows = core.db_fetchall(conn, """
        SELECT b.*, c.name AS customer_name, o.date, o.start_time, o.style, o.service, a.name AS artist_name
        FROM bookings b
        JOIN customers c ON c.id = b.customer_id
        JOIN openings o ON o.id = b.opening_id
        JOIN artists a ON a.id = b.artist_id
        WHERE o.shop_id = ? ORDER BY o.date DESC, o.start_time DESC
    """, (user["shop_id"],))
    conn.close()
    return {"bookings": [as_dict(row) for row in rows]}
