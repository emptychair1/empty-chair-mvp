"""Founder view of real Concierge pilots only."""
import html
import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import concierge_leads
import concierge_pilot

FOUNDER_EMAILS = {
    core.normalize_email(v)
    for v in os.getenv("EMPTY_CHAIR_FOUNDER_EMAILS", "").replace(";", ",").split(",")
    if core.normalize_email(v)
}
DEMO_NAMES = {"black lantern", "black lantern tattoo", "crybaby", "cry baby", "crybaby tattoo", "cry baby tattoo", "tattoo shop"}


def _e(v):
    return html.escape(str(v or ""), quote=True)


def _profile(raw):
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _founder(request):
    user = core.get_current_user(request)
    if not user:
        return None, core.login_required_redirect(request)[1]
    email = core.normalize_email(user["email"] if "email" in user.keys() else "")
    if not FOUNDER_EMAILS or email not in FOUNDER_EMAILS:
        return None, HTMLResponse("<h1>Founder access required</h1>", status_code=403)
    return user, None


def _real_pilot(config):
    name = str(config.get("display_name") or "").strip()
    emails = str(config.get("notification_emails") or "").strip()
    if not bool(config.get("enabled")) or not name or not emails:
        return False
    return name.lower() not in DEMO_NAMES


def _card(row):
    p = row.get("profile") or {}
    return f"""
    <article class='card'>
      <div class='row'><h3>{_e(row.get('name') or 'Concierge lead')}</h3><strong>{int(row.get('m4_confidence') or 0)}% M4</strong></div>
      <div class='muted'>{_e(row.get('phone') or 'No phone')} · {_e(row.get('email') or 'No email')}</div>
      <p>{_e(p.get('project') or 'No project description')}</p>
      <div class='facts'>
        <span><b>Style</b>{_e(p.get('styles') or 'Unknown')}</span>
        <span><b>Placement</b>{_e(p.get('placement') or 'Unknown')}</span>
        <span><b>Budget</b>{_e(p.get('budget') or 'Unknown')}</span>
        <span><b>Timing</b>{_e(p.get('timing') or 'Unknown')}</span>
        <span><b>Artist</b>{_e(p.get('artist_vibe') or 'No preference')}</span>
        <span><b>Contact</b>{_e(p.get('contact_preference') or 'Not specified')}</span>
      </div>
      <div class='muted foot'>Consent {'YES' if row.get('offer_opt_in') else 'NO'} · {_e(row.get('created_at') or '')}</div>
    </article>"""


def render(pilots):
    total = sum(len(p["leads"]) for p in pilots)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = 0
    for pilot in pilots:
        for lead in pilot["leads"]:
            try:
                dt = datetime.fromisoformat(str(lead.get("created_at") or "").replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    recent += 1
            except Exception:
                pass
    sections = []
    for pilot in pilots:
        cards = "".join(_card(x) for x in pilot["leads"]) or "<div class='empty'>No Concierge leads yet.</div>"
        sections.append(f"<section><div class='shop'><div><small>LIVE PILOT</small><h2>{_e(pilot['name'])}</h2></div><div>{len(pilot['leads'])} leads</div></div><div class='grid'>{cards}</div></section>")
    body = "".join(sections) or "<div class='empty'>No real pilot shops configured yet.</div>"
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='refresh' content='20'><title>Live Pilot Leads</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#080a08;color:#f0eadf;font-family:Inter,system-ui}}main{{max-width:1200px;margin:auto;padding:28px}}header,.shop,.row{{display:flex;justify-content:space-between;gap:16px;align-items:center}}header{{border-bottom:1px solid #293028;padding-bottom:20px}}h1{{font-size:40px;margin:4px 0}}h2{{margin:4px 0}}small,strong{{color:#d8ff45}}section{{padding:24px 0;border-bottom:1px solid #242a23}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}}.card{{border:1px solid #2b332a;background:#0d100d;padding:16px}}.card h3{{margin:0}}.muted{{color:#929a90;font-size:12px}}.facts{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}}.facts span{{border:1px solid #252b24;padding:8px;font-size:11px}}.facts b{{display:block;color:#777f75;font-size:9px;text-transform:uppercase}}.foot{{margin-top:12px}}.empty{{border:1px dashed #343c32;padding:24px;color:#858e82}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}.facts{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}</style></head><body><main><header><div><small>FOUNDER · REAL PILOTS ONLY</small><h1>Live Pilot Leads</h1><div class='muted'>Only configured client pilots. Demo/test shops are excluded.</div></div><div><strong>{total}</strong> total · <strong>{recent}</strong> last 24h</div></header>{body}</main></body></html>"""


@core.app.get("/pilot-leads-live", response_class=HTMLResponse)
def pilot_leads_live(request: Request):
    user, denied = _founder(request)
    if denied:
        return denied
    conn = core.connect()
    try:
        concierge_leads._ensure_table(conn)
        concierge_pilot._ensure_schema(conn)
        configs = [dict(r) for r in core.db_fetchall(conn, "SELECT * FROM concierge_pilot_config ORDER BY updated_at DESC")]
        configs = [c for c in configs if _real_pilot(c)]
        allowed = {str(c.get("shop_id") or "") for c in configs}
        rows = core.db_fetchall(conn, "SELECT l.*, c.name, c.phone, c.email FROM concierge_leads l LEFT JOIN customers c ON c.id=l.customer_id AND c.shop_id=l.shop_id ORDER BY l.created_at DESC LIMIT 1000")
        by_shop = {sid: [] for sid in allowed}
        for raw in rows:
            row = dict(raw)
            sid = str(row.get("shop_id") or "")
            if sid not in allowed:
                continue
            row["profile"] = _profile(row.get("profile_json"))
            by_shop[sid].append(row)
        pilots = [{"name": str(c.get("display_name") or "Tattoo Shop"), "leads": by_shop.get(str(c.get("shop_id") or ""), [])} for c in configs]
        return HTMLResponse(render(pilots), headers={"Cache-Control": "no-store"})
    finally:
        conn.close()
