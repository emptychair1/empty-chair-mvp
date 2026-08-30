"""Content attribution: per-asset Concierge campaigns, KPIs, and manual Meta scheduling state."""
import uuid
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse

import app as core
import demand_acquisition
import demand_content


def ensure_schema(conn):
    demand_content._ensure_tables(conn)
    demand_acquisition._ensure_tables(conn)
    for column, ddl in (
        ("acquisition_campaign_id", "TEXT"),
        ("manual_meta_scheduled", "INTEGER NOT NULL DEFAULT 0"),
        ("manual_meta_scheduled_at", "TEXT"),
    ):
        demand_content._ensure_column(conn, column, ddl)
    conn.commit()


def ensure_asset_campaign(conn, shop_id, asset_id, title="", hook=""):
    ensure_schema(conn)
    row = core.db_fetchone(conn, "SELECT acquisition_campaign_id FROM demand_content_assets WHERE id=? AND shop_id=?", (asset_id, shop_id))
    if not row:
        return None
    campaign_id = str(row["acquisition_campaign_id"] or "").strip()
    if campaign_id:
        existing = core.db_fetchone(conn, "SELECT id FROM acquisition_campaigns WHERE id=? AND shop_id=?", (campaign_id, shop_id))
        if existing:
            return campaign_id
    campaign_id = f"content_{asset_id}_{uuid.uuid4().hex[:8]}"
    now = core.now_iso()
    identity = core.db_fetchone(conn, "SELECT id FROM acquisition_identities WHERE owner_shop_id=? AND status='active' ORDER BY created_at DESC LIMIT 1", (shop_id,))
    identity_id = identity["id"] if identity else None
    core.db_execute(conn, """INSERT INTO acquisition_campaigns(id,shop_id,artist_id,identity_id,name,channel,hook,status,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""", (campaign_id, shop_id, None, identity_id, f"Content · {title or asset_id}", "instagram_content", hook or "Instagram portfolio content", "active", now, now))
    core.db_execute(conn, "UPDATE demand_content_assets SET acquisition_campaign_id=? WHERE id=? AND shop_id=?", (campaign_id, asset_id, shop_id))
    conn.commit()
    return campaign_id


def tracked_url(base_url, shop_id, campaign_id):
    params = urlencode({"shop_id": shop_id, "campaign_id": campaign_id, "src": "instagram_content"})
    return f"{base_url.rstrip('/')}/a/{campaign_id}?{params}"


def kpis(conn, shop_id):
    ensure_schema(conn)
    demand_acquisition._ensure_lead_attribution_columns(conn)
    row = core.db_fetchone(conn, """SELECT
        (SELECT COUNT(*) FROM demand_content_assets WHERE shop_id=? AND status='published') AS posts,
        (SELECT COUNT(*) FROM acquisition_visits WHERE shop_id=? AND source='instagram_content') AS visits,
        (SELECT COUNT(*) FROM concierge_leads WHERE shop_id=? AND acquisition_source='instagram_content') AS leads
    """, (shop_id, shop_id, shop_id))
    posts, visits, leads = int(row["posts"] or 0), int(row["visits"] or 0), int(row["leads"] or 0)
    return {"posts": posts, "visits": visits, "leads": leads, "lead_rate": round((leads / visits * 100), 1) if visits else 0}


@core.app.post("/demand-acquisition/content/{asset_id}/manual-meta-scheduled")
def manual_meta_scheduled(asset_id: int, request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        ensure_schema(conn)
        core.db_execute(conn, "UPDATE demand_content_assets SET manual_meta_scheduled=1,manual_meta_scheduled_at=? WHERE id=? AND shop_id=?", (core.now_iso(), asset_id, user["shop_id"]))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/demand-acquisition/content/calendar", status_code=303)
