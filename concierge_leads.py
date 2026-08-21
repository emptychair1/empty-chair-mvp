"""Persistent Concierge lead capture and in-app lead review."""
import json
import uuid

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

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
    """Persist a customer record and the richer Concierge profile."""
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
            customer_id,
            shop_id,
            profile.get("name") or "Concierge lead",
            profile.get("phone") or "000-000-0000",
            profile.get("email") or None,
            consent,
            profile.get("artist_vibe") or "",
            profile.get("styles") or "",
            "tattoo",
            0,0,0,0,0,None,None,now,now,
        ))
        core.db_execute(conn, """
            INSERT INTO concierge_leads(
                id,shop_id,customer_id,source,profile_json,m4_confidence,
                offer_opt_in,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            lead_id, shop_id, customer_id, "concierge", json.dumps(profile),
            int(confidence), consent, now, now,
        ))
        conn.commit()
        return customer_id, lead_id
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
        rows = core.db_fetchall(conn, """
            SELECT l.*, c.name, c.phone, c.email, c.communication_consent,
                   c.preferred_styles, c.preferred_artists
            FROM concierge_leads l
            JOIN customers c ON c.id=l.customer_id
            WHERE l.shop_id=?
            ORDER BY l.created_at DESC
            LIMIT 250
        """, (user["shop_id"],))
    finally:
        conn.close()

    cards = []
    for row in rows:
        r = dict(row)
        try:
            p = json.loads(r.get("profile_json") or "{}")
        except Exception:
            p = {}
        consent = "YES" if r.get("communication_consent") else "NO"
        cards.append(f'''<article class="lead">
          <div class="leadtop"><div><b>{r.get('name') or 'Unnamed lead'}</b><span>{r.get('email') or 'No email'} · {r.get('phone') or 'No phone'}</span></div><div class="score">{r.get('m4_confidence',0)}% M4</div></div>
          <div class="chips"><i>Consent {consent}</i><i>{p.get('styles') or 'Style unknown'}</i><i>{p.get('budget') or 'Budget unknown'}</i><i>{p.get('timing') or 'Timing unknown'}</i></div>
          <p>{p.get('project') or 'No project description yet.'}</p>
          <small>Short notice: {p.get('short_notice') or 'unknown'} · Placement: {p.get('placement') or 'unknown'} · Travel: {p.get('travel') or 'unknown'} · Artist fit: {p.get('artist_vibe') or 'unknown'}</small>
        </article>''')
    body = "".join(cards) or '<div class="empty">No Concierge leads yet.</div>'
    html = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Concierge Leads</title><style>
    :root{{--g:#a6ff2e;--bg:#070907;--panel:#0d110d;--line:#283228;--ink:#edf4e9;--muted:#8b9588}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,system-ui,sans-serif}}.wrap{{max-width:1180px;margin:auto;padding:26px}}header{{display:flex;justify-content:space-between;gap:18px;align-items:center;border-bottom:1px solid var(--line);padding-bottom:18px}}h1{{margin:24px 0 8px;font-size:42px}}.sub{{color:var(--muted);margin-bottom:22px}}a{{color:var(--g);text-decoration:none}}.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}.lead{{border:1px solid var(--line);background:var(--panel);padding:18px}}.leadtop{{display:flex;justify-content:space-between;gap:12px}}.lead b{{font-size:18px}}.lead span,.lead small{{display:block;color:var(--muted);font-size:11px;margin-top:5px;line-height:1.5}}.score{{color:var(--g);font-weight:900}}.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0}}.chips i{{font-style:normal;border:1px solid #344034;padding:5px 7px;font-size:10px;color:#b9c3b5}}.lead p{{line-height:1.5}}.empty{{border:1px dashed var(--line);padding:30px;color:var(--muted)}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}h1{{font-size:34px}}}}
    </style></head><body><div class="wrap"><header><b>EMPTY CHAIR / CONCIERGE</b><a href="/dashboard">Back to dashboard</a></header><h1>Concierge leads</h1><div class="sub">Customer profiles created by Concierge, including explicit contact consent and zero-party tattoo signals.</div><section class="grid">{body}</section></div></body></html>'''
    return HTMLResponse(html, headers={"Cache-Control":"no-store"})
