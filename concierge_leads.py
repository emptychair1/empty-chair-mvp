"""Persistent Concierge lead capture and in-app lead review."""
import html
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

    # The first Concierge builds used a runtime-created table. Production may
    # therefore contain an older version of the table. Migrate it in place.
    required = {
        "source": "TEXT NOT NULL DEFAULT 'concierge'",
        "profile_json": "TEXT NOT NULL DEFAULT '{}'",
        "m4_confidence": "INTEGER NOT NULL DEFAULT 0",
        "offer_opt_in": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    if getattr(core, "USE_POSTGRES", False):
        for column, ddl in required.items():
            core.db_execute(conn, f"ALTER TABLE concierge_leads ADD COLUMN IF NOT EXISTS {column} {ddl}")
        conn.commit()
    else:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(concierge_leads)").fetchall()}
        for column, ddl in required.items():
            if column not in existing:
                core.db_execute(conn, f"ALTER TABLE concierge_leads ADD COLUMN {column} {ddl}")
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
        """, (
            lead_id, shop_id, customer_id, "concierge", json.dumps(profile),
            int(confidence), consent, now, now,
        ))
        conn.commit()

        # Do not report success unless both persistent records can be read back.
        customer = core.db_fetchone(conn, "SELECT id FROM customers WHERE id=? AND shop_id=?", (customer_id, shop_id))
        lead = core.db_fetchone(conn, "SELECT id FROM concierge_leads WHERE id=? AND shop_id=?", (lead_id, shop_id))
        if not customer or not lead:
            raise RuntimeError("Concierge persistence verification failed")
        return customer_id, lead_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _e(value):
    return html.escape(str(value or ""), quote=True)


def _render_leads(shop, leads):
    shop_name = _e(shop["name"] if shop else "Studio")
    cards = []
    for lead in leads:
        profile = lead.get("profile") or {}
        name = _e(lead.get("name") or "Concierge lead")
        email = _e(lead.get("email") or "No email")
        phone = _e(lead.get("phone") or "No phone")
        consent = "YES" if lead.get("communication_consent") else "NO"
        styles = _e(profile.get("styles") or lead.get("preferred_styles") or "Style unknown")
        budget = _e(profile.get("budget") or "Budget unknown")
        timing = _e(profile.get("timing") or "Timing unknown")
        project = _e(profile.get("project") or "No project description yet.")
        placement = _e(profile.get("placement") or "unknown")
        short_notice = _e(profile.get("short_notice") or "unknown")
        travel = _e(profile.get("travel") or "unknown")
        artist = _e(profile.get("artist_vibe") or lead.get("preferred_artists") or "unknown")
        score = int(lead.get("m4_confidence") or 0)
        cards.append(f"""
        <article class='card'>
          <div class='top'><div><h2>{name}</h2><div class='muted'>{email} · {phone}</div></div><strong>{score}% M4</strong></div>
          <div class='chips'><span>Consent {consent}</span><span>{styles}</span><span>{budget}</span><span>{timing}</span></div>
          <p>{project}</p>
          <div class='muted'>Short notice: {short_notice} · Placement: {placement} · Travel: {travel} · Artist fit: {artist}</div>
        </article>""")
    body = "".join(cards) if cards else "<div class='empty'>No Concierge leads yet.</div>"
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Concierge Leads · Empty Chair</title><link rel='stylesheet' href='/static/style.css'><style>
    body{{background:#080a08;color:#f0eadf;font-family:Inter,system-ui,sans-serif;margin:0}}.wrap{{max-width:1180px;margin:auto;padding:28px}}.head{{display:flex;justify-content:space-between;gap:18px;align-items:end;margin-bottom:22px;border-bottom:1px solid #2a3028;padding-bottom:18px}}h1{{font-size:42px;margin:4px 0}}.ey{{color:#d8ff45;font:700 10px ui-monospace,monospace;letter-spacing:.14em}}.muted{{color:#8f978c;font-size:12px;line-height:1.5}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.card{{border:1px solid #2a3028;background:#0e110e;padding:18px}}.top{{display:flex;justify-content:space-between;gap:12px}}.top h2{{font-size:18px;margin:0 0 5px}}.top strong{{color:#d8ff45}}.chips{{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0}}.chips span{{border:1px solid #323932;padding:5px 7px;font-size:10px}}.btn{{display:inline-block;text-decoration:none;background:#d8ff45;color:#10130f;padding:11px 14px;font-weight:900}}.back{{color:#f0eadf;text-decoration:none;margin-right:10px}}.empty{{border:1px dashed #323932;padding:28px;color:#8f978c}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}.head{{align-items:start;flex-direction:column}}h1{{font-size:34px}}}}
    </style></head><body><main class='wrap'><div class='head'><div><div class='ey'>CUSTOMER ACQUISITION</div><h1>Concierge Leads</h1><div class='muted'>{shop_name} · Profiles created by Concierge with explicit zero-party signals.</div></div><div><a class='back' href='/'>← App</a><a class='btn' href='/concierge'>Open Concierge</a></div></div><section class='grid'>{body}</section></main></body></html>"""


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
            LEFT JOIN customers c ON c.id=l.customer_id AND c.shop_id=l.shop_id
            WHERE l.shop_id=?
            ORDER BY l.created_at DESC
            LIMIT 250
        """, (user["shop_id"],))
        leads = []
        for row in rows:
            r = dict(row)
            try:
                r["profile"] = json.loads(r.get("profile_json") or "{}")
            except Exception:
                r["profile"] = {}
            leads.append(r)
        return HTMLResponse(_render_leads(shop, leads), headers={"Cache-Control": "no-store"})
    except Exception as exc:
        conn.rollback()
        # A controlled diagnostic is much more useful than an opaque 500 while
        # this new screen is being piloted.
        return HTMLResponse(
            "<!doctype html><html><body style='background:#080a08;color:#f0eadf;font-family:system-ui;padding:32px'><h1>Concierge Leads could not load</h1><pre style='white-space:pre-wrap'>" + _e(type(exc).__name__ + ": " + str(exc)) + "</pre><a style='color:#d8ff45' href='/'>Back to app</a></body></html>",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    finally:
        conn.close()
