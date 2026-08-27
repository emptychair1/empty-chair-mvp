"""Demand Acquisition V1: tracked acquisition links and campaign attribution."""
import html
import json
import uuid
from urllib.parse import urlencode

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core


def _e(value):
    return html.escape(str(value or ""), quote=True)


def _ensure_tables(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS acquisition_campaigns (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            artist_id TEXT,
            name TEXT NOT NULL,
            channel TEXT NOT NULL,
            hook TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS acquisition_visits (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            shop_id TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()


def record_lead_attribution(conn, lead_id, campaign_id, source):
    """Attach acquisition provenance to a Concierge lead without breaking old databases."""
    if not campaign_id and not source:
        return
    if getattr(core, "USE_POSTGRES", False):
        core.db_execute(conn, "ALTER TABLE concierge_leads ADD COLUMN IF NOT EXISTS campaign_id TEXT")
        core.db_execute(conn, "ALTER TABLE concierge_leads ADD COLUMN IF NOT EXISTS acquisition_source TEXT NOT NULL DEFAULT ''")
    else:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(concierge_leads)").fetchall()}
        if "campaign_id" not in columns:
            core.db_execute(conn, "ALTER TABLE concierge_leads ADD COLUMN campaign_id TEXT")
        if "acquisition_source" not in columns:
            core.db_execute(conn, "ALTER TABLE concierge_leads ADD COLUMN acquisition_source TEXT NOT NULL DEFAULT ''")
    core.db_execute(
        conn,
        "UPDATE concierge_leads SET campaign_id=?, acquisition_source=? WHERE id=?",
        (campaign_id or None, source or "", lead_id),
    )
    conn.commit()


def _campaign_url(request, campaign):
    base = str(request.base_url).rstrip("/")
    params = urlencode({
        "shop_id": campaign["shop_id"],
        "campaign_id": campaign["id"],
        "src": campaign["channel"],
    })
    return f"{base}/a/{campaign['id']}?{params}"


@core.app.get("/a/{campaign_id}")
def acquisition_entry(campaign_id: str):
    conn = core.connect()
    try:
        _ensure_tables(conn)
        campaign = core.db_fetchone(conn, "SELECT * FROM acquisition_campaigns WHERE id=? AND status='active'", (campaign_id,))
        if not campaign:
            return RedirectResponse("/concierge", status_code=302)
        core.db_execute(conn, "INSERT INTO acquisition_visits(id,campaign_id,shop_id,source,created_at) VALUES (?,?,?,?,?)", (
            f"visit_{uuid.uuid4().hex[:12]}", campaign_id, campaign["shop_id"], campaign["channel"], core.now_iso()
        ))
        conn.commit()
        params = urlencode({"shop_id": campaign["shop_id"], "campaign_id": campaign_id, "src": campaign["channel"]})
        return RedirectResponse(f"/concierge?{params}", status_code=302)
    finally:
        conn.close()


@core.app.get("/demand-acquisition", response_class=HTMLResponse)
def demand_acquisition_dashboard(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        campaigns = core.db_fetchall(conn, """
            SELECT c.*,
                   (SELECT COUNT(*) FROM acquisition_visits v WHERE v.campaign_id=c.id) AS visits,
                   (SELECT COUNT(*) FROM concierge_leads l WHERE l.shop_id=c.shop_id AND l.campaign_id=c.id) AS leads
            FROM acquisition_campaigns c
            WHERE c.shop_id=?
            ORDER BY c.created_at DESC
        """, (user["shop_id"],))
    except Exception:
        conn.rollback()
        campaigns = []
    finally:
        conn.close()

    cards = []
    for c in campaigns:
        url = _campaign_url(request, c)
        cards.append(f"<article><b>{_e(c['name'])}</b><span>{_e(c['channel'])}</span><p>{_e(c['hook'])}</p><small>{int(c['visits'] or 0)} visits · {int(c['leads'] or 0)} leads</small><input value='{_e(url)}' readonly onclick='this.select()'></article>")
    body = "".join(cards) or "<p class='empty'>No campaigns yet. Create the first Marketplace campaign below.</p>"
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Demand Acquisition · Empty Chair</title><style>
body{{margin:0;background:#080a08;color:#f0eadf;font-family:Inter,system-ui,sans-serif}}main{{max-width:1000px;margin:auto;padding:30px}}h1{{font-size:42px;margin:5px 0}}.ey{{color:#d8ff45;font:700 11px monospace;letter-spacing:.15em}}form,article{{border:1px solid #30362e;background:#0e110e;padding:18px;margin:14px 0}}label{{display:block;font-size:11px;color:#9ba197;margin-top:12px}}input,select,textarea{{box-sizing:border-box;width:100%;padding:11px;margin-top:5px;background:#090b09;color:#f0eadf;border:1px solid #353c33}}button{{margin-top:15px;padding:12px 18px;background:#d8ff45;border:0;font-weight:900}}article span{{float:right;color:#d8ff45;font:700 11px monospace;text-transform:uppercase}}article input{{font:11px monospace}}small{{color:#9ba197}}a{{color:#d8ff45}}.empty{{color:#9ba197}}</style></head><body><main><a href='/'>← App</a><div class='ey'>M4 · CUSTOMER ACQUISITION</div><h1>Demand Acquisition</h1><p>Create tracked campaigns. Post them manually on Marketplace or other channels; Empty Chair owns everything after the click.</p><form method='post' action='/demand-acquisition/campaigns'><label>CAMPAIGN NAME</label><input name='name' required placeholder='Traditional tattoos — Athens'><label>CHANNEL</label><select name='channel'><option value='facebook_marketplace'>Facebook Marketplace</option><option value='facebook_group'>Facebook Group</option><option value='instagram'>Instagram</option><option value='qr'>QR / Physical</option><option value='other'>Other</option></select><label>HOOK / OFFER</label><textarea name='hook' required placeholder='Traditional tattoo openings — custom or flash'></textarea><button>Create tracked campaign</button></form><section>{body}</section></main></body></html>""", headers={"Cache-Control":"no-store"})


@core.app.post("/demand-acquisition/campaigns")
def create_acquisition_campaign(request: Request, name: str = Form(...), channel: str = Form(...), hook: str = Form(...), artist_id: str = Form("")):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    campaign_id = f"camp_{uuid.uuid4().hex[:12]}"
    now = core.now_iso()
    conn = core.connect()
    try:
        _ensure_tables(conn)
        core.db_execute(conn, "INSERT INTO acquisition_campaigns(id,shop_id,artist_id,name,channel,hook,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (
            campaign_id, user["shop_id"], artist_id.strip() or None, name.strip(), channel.strip(), hook.strip(), "active", now, now
        ))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/demand-acquisition", status_code=303)
