"""Founder-only cross-shop Concierge pilot lead dashboard."""

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
    core.normalize_email(value)
    for value in os.getenv("EMPTY_CHAIR_FOUNDER_EMAILS", "").replace(";", ",").split(",")
    if core.normalize_email(value)
}


def _e(value):
    return html.escape(str(value or ""), quote=True)


def _founder_user(request: Request):
    user = core.get_current_user(request)
    if not user:
        return None, core.login_required_redirect(request)[1]

    email = core.normalize_email(user["email"] if "email" in user.keys() else "")
    if not FOUNDER_EMAILS or email not in FOUNDER_EMAILS:
        return None, HTMLResponse(
            "<!doctype html><html><body style='background:#080a08;color:#f0eadf;font-family:system-ui;padding:32px'>"
            "<h1>Founder access required</h1>"
            "<p>This dashboard contains customer data across pilot shops.</p>"
            "<p>Set <code>EMPTY_CHAIR_FOUNDER_EMAILS</code> to the authorized login email, then redeploy.</p>"
            "</body></html>",
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )
    return user, None


def _parse_profile(raw):
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _format_time(value):
    if not value:
        return "Unknown time"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%b %d · %I:%M %p UTC")
    except Exception:
        return str(value)


def _lead_card(lead):
    profile = lead.get("profile") or {}
    name = _e(lead.get("name") or "Concierge lead")
    phone = _e(lead.get("phone") or "No phone")
    email = _e(lead.get("email") or "No email")
    project = _e(profile.get("project") or "No project description")
    styles = _e(profile.get("styles") or "Unknown")
    placement = _e(profile.get("placement") or "Unknown")
    budget = _e(profile.get("budget") or "Unknown")
    timing = _e(profile.get("timing") or "Unknown")
    artist = _e(profile.get("artist_vibe") or "No preference")
    contact = _e(profile.get("contact_preference") or "Not specified")
    score = int(lead.get("m4_confidence") or 0)
    consent = "YES" if lead.get("offer_opt_in") else "NO"
    created = _e(_format_time(lead.get("created_at")))

    return f"""
    <article class='lead-card'>
      <div class='lead-top'>
        <div>
          <h3>{name}</h3>
          <div class='muted'>{phone} · {email}</div>
        </div>
        <div class='score'>{score}%</div>
      </div>
      <p class='project'>{project}</p>
      <div class='facts'>
        <span><b>Style</b>{styles}</span>
        <span><b>Placement</b>{placement}</span>
        <span><b>Budget</b>{budget}</span>
        <span><b>Timing</b>{timing}</span>
        <span><b>Artist</b>{artist}</span>
        <span><b>Contact</b>{contact}</span>
      </div>
      <div class='lead-foot'><span>Consent {consent}</span><span>{created}</span></div>
    </article>
    """


def _render_dashboard(pilots, total_leads, last_24h):
    sections = []
    for pilot in pilots:
        leads = pilot.get("leads") or []
        cards = "".join(_lead_card(lead) for lead in leads)
        if not cards:
            cards = "<div class='empty'>No Concierge leads yet.</div>"
        sections.append(f"""
        <section class='shop'>
          <div class='shop-head'>
            <div>
              <div class='ey'>PILOT SHOP</div>
              <h2>{_e(pilot.get('display_name'))}</h2>
              <div class='muted'>{pilot.get('last_24h', 0)} in last 24h · {pilot.get('total', 0)} total</div>
            </div>
            <div class='live'><i></i>{'LIVE' if pilot.get('enabled') else 'PAUSED'}</div>
          </div>
          <div class='lead-grid'>{cards}</div>
        </section>
        """)

    body = "".join(sections) if sections else "<div class='empty'>No pilot shops are configured yet.</div>"
    return f"""<!doctype html>
<html><head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<meta http-equiv='refresh' content='20'>
<title>Pilot Leads · Empty Chair</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#080a08;color:#f0eadf;font-family:Inter,system-ui,-apple-system,sans-serif}}.wrap{{max-width:1280px;margin:auto;padding:28px}}.topbar{{display:flex;justify-content:space-between;gap:20px;align-items:end;padding-bottom:22px;border-bottom:1px solid #293028}}.ey{{color:#d8ff45;font:800 10px ui-monospace,monospace;letter-spacing:.16em}}h1{{font-size:44px;margin:5px 0 4px}}h2{{font-size:28px;margin:4px 0}}h3{{font-size:18px;margin:0 0 5px}}.muted{{color:#929a90;font-size:12px;line-height:1.45}}.stats{{display:flex;gap:9px;flex-wrap:wrap}}.stat{{min-width:110px;border:1px solid #2b332a;background:#0e110e;padding:12px 14px}}.stat strong{{display:block;font-size:25px;color:#d8ff45}}.stat span{{font-size:10px;color:#929a90;text-transform:uppercase;letter-spacing:.08em}}.shop{{padding:28px 0;border-bottom:1px solid #242a23}}.shop-head{{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:15px}}.live{{font:800 10px ui-monospace,monospace;letter-spacing:.13em;color:#b8c1b5}}.live i{{display:inline-block;width:7px;height:7px;border-radius:50%;background:#d8ff45;margin-right:7px}}.lead-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.lead-card{{border:1px solid #2b332a;background:#0d100d;padding:17px}}.lead-top{{display:flex;justify-content:space-between;gap:12px;align-items:start}}.score{{font-weight:900;color:#d8ff45;border:1px solid #394137;padding:5px 7px}}.project{{font-size:14px;line-height:1.5;margin:14px 0}}.facts{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}}.facts span{{border:1px solid #252b24;padding:8px;color:#d7d8d3;font-size:11px;overflow:hidden}}.facts b{{display:block;color:#777f75;font-size:9px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}}.lead-foot{{display:flex;justify-content:space-between;gap:10px;color:#777f75;font-size:10px;margin-top:13px;padding-top:10px;border-top:1px solid #222720}}.empty{{border:1px dashed #343c32;color:#858e82;padding:25px}}a{{color:#d8ff45;text-decoration:none;font-weight:800}}@media(max-width:800px){{.topbar,.shop-head{{align-items:flex-start;flex-direction:column}}.lead-grid{{grid-template-columns:1fr}}.facts{{grid-template-columns:repeat(2,minmax(0,1fr))}}h1{{font-size:35px}}}}
</style>
</head><body><main class='wrap'>
<div class='topbar'>
  <div><div class='ey'>FOUNDER · LIVE CUSTOMER SIGNALS</div><h1>Pilot Leads</h1><div class='muted'>All completed Concierge leads across active pilot shops. Auto-refreshes every 20 seconds.</div></div>
  <div class='stats'><div class='stat'><strong>{total_leads}</strong><span>Total leads</span></div><div class='stat'><strong>{last_24h}</strong><span>Last 24 hours</span></div><div class='stat'><strong>{len(pilots)}</strong><span>Pilot shops</span></div></div>
</div>
{body}
<div style='padding:22px 0'><a href='/concierge-pilot'>← Concierge pilot setup</a></div>
</main></body></html>"""


@core.app.get("/pilot-leads", response_class=HTMLResponse)
def pilot_leads_dashboard(request: Request):
    user, denied = _founder_user(request)
    if denied:
        return denied

    conn = core.connect()
    try:
        concierge_leads._ensure_table(conn)
        concierge_pilot._ensure_schema(conn)

        configs = core.db_fetchall(
            conn,
            """
            SELECT p.shop_id, p.display_name, p.public_token, p.enabled,
                   COALESCE(s.name, '') AS internal_shop_name
            FROM concierge_pilot_config p
            LEFT JOIN shops s ON s.id=p.shop_id
            ORDER BY p.created_at ASC
            """,
        )

        rows = core.db_fetchall(
            conn,
            """
            SELECT l.*, c.name, c.phone, c.email
            FROM concierge_leads l
            LEFT JOIN customers c ON c.id=l.customer_id AND c.shop_id=l.shop_id
            ORDER BY l.created_at DESC
            LIMIT 1000
            """,
        )

        by_shop = {}
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        total_leads = 0
        last_24h = 0

        for row in rows:
            item = dict(row)
            item["profile"] = _parse_profile(item.get("profile_json"))
            total_leads += 1
            try:
                created = datetime.fromisoformat(str(item.get("created_at") or "").replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created >= cutoff:
                    last_24h += 1
            except Exception:
                pass
            by_shop.setdefault(str(item.get("shop_id") or ""), []).append(item)

        pilots = []
        for row in configs:
            config = dict(row)
            shop_id = str(config.get("shop_id") or "")
            leads = by_shop.get(shop_id, [])
            recent = 0
            for lead in leads:
                try:
                    created = datetime.fromisoformat(str(lead.get("created_at") or "").replace("Z", "+00:00"))
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if created >= cutoff:
                        recent += 1
                except Exception:
                    pass
            pilots.append({
                "shop_id": shop_id,
                "display_name": str(config.get("display_name") or config.get("internal_shop_name") or "Tattoo Shop"),
                "enabled": bool(config.get("enabled")),
                "total": len(leads),
                "last_24h": recent,
                "leads": leads,
            })

        return HTMLResponse(
            _render_dashboard(pilots, total_leads, last_24h),
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return HTMLResponse(
            "<!doctype html><html><body style='background:#080a08;color:#f0eadf;font-family:system-ui;padding:32px'>"
            "<h1>Pilot Leads could not load</h1><pre style='white-space:pre-wrap'>" + _e(type(exc).__name__ + ": " + str(exc)) + "</pre></body></html>",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    finally:
        conn.close()
