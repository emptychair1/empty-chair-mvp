"""Persistent Concierge lead capture and in-app lead review."""
import json
import uuid

from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core

DEMO_SHOP_ID = "shop_live_demo"


def _ensure_table(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS concierge_leads (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'concierge',
            profile_json TEXT NOT NULL DEFAULT '{}',
            m4_confidence INTEGER NOT NULL DEFAULT 0,
            offer_opt_in INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()


def save_concierge_profile(shop_id, profile, confidence):
    now = core.now_iso()
    customer_id = f"conc_customer_{uuid.uuid4().hex[:12]}"
    lead_id = f"conc_lead_{uuid.uuid4().hex[:12]}"
    consent = 1 if profile.get("offer_opt_in") else 0
    conn = core.connect()
    try:
        _ensure_table(conn)
        core.db_execute(conn, """
            INSERT INTO customers(
                id,shop_id,name,phone,email,communication_consent,
                preferred_artists,preferred_styles,preferred_services,
                appointment_count,completed_count,cancellation_count,no_show_count,
                average_spend,last_appointment_at,last_offer_at,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            customer_id, shop_id, profile.get("name") or "Concierge lead",
            profile.get("phone") or "000-000-0000", profile.get("email") or None,
            consent, profile.get("artist_vibe") or "", profile.get("styles") or "",
            "tattoo", 0, 0, 0, 0, 0, None, None, now, now,
        ))
        core.db_execute(conn, """
            INSERT INTO concierge_leads(
                id,shop_id,customer_id,source,profile_json,m4_confidence,
                offer_opt_in,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
        """, (lead_id, shop_id, customer_id, "concierge", json.dumps(profile), int(confidence), consent, now, now))
        conn.commit()
        return customer_id, lead_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@core.app.get("/concierge-leads", response_class=HTMLResponse)
def concierge_leads_screen(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_table(conn)
        shop = core.db_fetchone(conn, "SELECT * FROM shops WHERE id=?", (user["shop_id"],))
        rows = core.db_fetchall(conn, """
            SELECT l.*, c.name, c.phone, c.email, c.communication_consent,
                   c.preferred_styles, c.preferred_artists
            FROM concierge_leads l
            JOIN customers c ON c.id=l.customer_id
            WHERE l.shop_id=? AND c.shop_id=?
            ORDER BY l.created_at DESC
            LIMIT 250
        """, (user["shop_id"], user["shop_id"]))
    finally:
        conn.close()

    leads = []
    for row in rows:
        r = dict(row)
        try:
            r["profile"] = json.loads(r.get("profile_json") or "{}")
        except Exception:
            r["profile"] = {}
        leads.append(r)

    return core.templates.TemplateResponse(
        request=request,
        name="concierge_leads.html",
        context={
            "user": user,
            "shop": shop,
            "leads": leads,
            "active_page": "concierge_leads",
        },
        headers={"Cache-Control": "no-store"},
    )
