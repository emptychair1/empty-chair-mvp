"""One-week Concierge pilot: iframe embed, notification emails, and automatic lead handoff."""

import html
import json
import secrets

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core
import notifications


app = core.app


def _ensure_schema(conn):
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS concierge_pilot_config (
            shop_id TEXT PRIMARY KEY,
            public_token TEXT NOT NULL UNIQUE,
            notification_emails TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
    )
    conn.commit()


def _normalize_emails(raw: str):
    values = []
    for piece in (raw or "").replace(";", ",").split(","):
        email = core.normalize_email(piece.strip())
        if email and email not in values:
            values.append(email)
    return values[:10]


def _config_for_shop(shop_id: str, create: bool = False):
    conn = core.connect()
    try:
        _ensure_schema(conn)
        row = core.db_fetchone(conn, "SELECT * FROM concierge_pilot_config WHERE shop_id=?", (shop_id,))
        if row or not create:
            return dict(row) if row else None
        now = core.now_iso()
        token = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12]
        core.db_execute(
            conn,
            "INSERT INTO concierge_pilot_config(shop_id,public_token,notification_emails,enabled,created_at,updated_at) VALUES (?,?,?,1,?,?)",
            (shop_id, token, "", now, now),
        )
        conn.commit()
        row = core.db_fetchone(conn, "SELECT * FROM concierge_pilot_config WHERE shop_id=?", (shop_id,))
        return dict(row)
    finally:
        conn.close()


def shop_for_public_token(token: str):
    conn = core.connect()
    try:
        _ensure_schema(conn)
        row = core.db_fetchone(
            conn,
            "SELECT shop_id FROM concierge_pilot_config WHERE public_token=? AND enabled=1 LIMIT 1",
            ((token or "").strip(),),
        )
        return str(row["shop_id"]) if row else None
    finally:
        conn.close()


def send_new_lead_email(shop_id: str, profile: dict, confidence: int, customer_id: str = ""):
    config = _config_for_shop(shop_id, create=False)
    if not config or not int(config.get("enabled") or 0):
        return False
    recipients = _normalize_emails(config.get("notification_emails") or "")
    if not recipients:
        return False

    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT name FROM shops WHERE id=?", (shop_id,))
    finally:
        conn.close()
    shop_name = str(shop["name"] if shop else "Your shop")

    def e(value):
        return html.escape(str(value or "Not specified"))

    consent = "YES" if profile.get("offer_opt_in") else "NO"
    subject_name = profile.get("name") or "New lead"
    subject = f"New Concierge lead: {subject_name}"
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;line-height:1.55;color:#171917">
      <div style="font-size:12px;letter-spacing:.08em;color:#697066">EMPTY CHAIR CONCIERGE</div>
      <h2 style="margin:8px 0 4px">New lead for {e(shop_name)}</h2>
      <p style="margin-top:0;color:#687066">Concierge captured this directly from the customer.</p>
      <table style="width:100%;border-collapse:collapse">
        <tr><td style="padding:8px 0;color:#777;width:150px">Name</td><td><strong>{e(profile.get('name'))}</strong></td></tr>
        <tr><td style="padding:8px 0;color:#777">Phone</td><td>{e(profile.get('phone'))}</td></tr>
        <tr><td style="padding:8px 0;color:#777">Email</td><td>{e(profile.get('email'))}</td></tr>
        <tr><td style="padding:8px 0;color:#777">Project</td><td>{e(profile.get('project'))}</td></tr>
        <tr><td style="padding:8px 0;color:#777">Style</td><td>{e(profile.get('styles'))}</td></tr>
        <tr><td style="padding:8px 0;color:#777">Placement</td><td>{e(profile.get('placement'))}</td></tr>
        <tr><td style="padding:8px 0;color:#777">Budget</td><td>{e(profile.get('budget'))}</td></tr>
        <tr><td style="padding:8px 0;color:#777">Timing</td><td>{e(profile.get('timing'))}</td></tr>
        <tr><td style="padding:8px 0;color:#777">Artist / vibe</td><td>{e(profile.get('artist_vibe'))}</td></tr>
        <tr><td style="padding:8px 0;color:#777">Preferred contact</td><td>{e(profile.get('contact_preference'))}</td></tr>
        <tr><td style="padding:8px 0;color:#777">Contact permission</td><td><strong>{consent}</strong></td></tr>
        <tr><td style="padding:8px 0;color:#777">Profile completeness</td><td>{int(confidence or 0)}%</td></tr>
      </table>
      <p style="margin-top:24px;color:#777;font-size:12px">Customer ID: {e(customer_id)}</p>
    </div>
    """

    sent = False
    for recipient in recipients:
        try:
            sent = bool(notifications.send_email(recipient, subject, body)) or sent
        except Exception as exc:
            core.event("concierge.lead_email_failed", "customer", customer_id or shop_id, str(exc))
    if sent:
        core.event("concierge.lead_emailed", "customer", customer_id or shop_id, json.dumps({"recipients": recipients}))
    return sent


def _render_concierge(shop_id: str):
    with open("templates/concierge_chat.html", "r", encoding="utf-8") as handle:
        page = handle.read()
    page = page.replace("{{ url_for('static', path='/concierge-chat.css') }}", "/static/concierge-chat.css")
    page = page.replace("{{ url_for('static', path='/concierge-chat.js') }}", "/static/concierge-chat.js")
    page = page.replace("{{ shop_id|tojson }}", json.dumps(shop_id))
    return HTMLResponse(
        page,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "frame-ancestors *",
        },
    )


@app.get("/c/{token}", response_class=HTMLResponse)
def concierge_public_embed(token: str):
    shop_id = shop_for_public_token(token)
    if not shop_id:
        return HTMLResponse("<h1>Concierge link is inactive.</h1>", status_code=404)
    return _render_concierge(shop_id)


@app.get("/concierge-pilot", response_class=HTMLResponse)
def concierge_pilot_settings(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    config = _config_for_shop(str(user["shop_id"]), create=True)
    token = config["public_token"]
    public_url = f"{core.PUBLIC_BASE_URL.rstrip('/')}/c/{token}"
    embed = f'<iframe src="{public_url}" title="Tattoo Concierge" style="width:100%;min-height:780px;border:0" loading="lazy"></iframe>'
    emails = html.escape(config.get("notification_emails") or "")
    checked = "checked" if int(config.get("enabled") or 0) else ""
    page = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Concierge Pilot</title><link rel='stylesheet' href='/static/style.css'><style>body{{background:#080908;color:#f2eee5;font-family:Inter,system-ui;margin:0}}main{{max-width:850px;margin:auto;padding:28px}}section{{border:1px solid #2b3029;background:#0e110e;padding:22px;margin:14px 0}}label{{display:block;margin:14px 0 6px;font-weight:700}}input[type=email],input[type=text],textarea{{width:100%;box-sizing:border-box;background:#080a08;color:#f2eee5;border:1px solid #384036;padding:12px;font-size:16px}}textarea{{min-height:120px}}button{{background:#b7ff3c;color:#0b0e09;border:0;padding:12px 16px;font-weight:900;cursor:pointer}}code{{word-break:break-all;color:#dfffb0}}.muted{{color:#929a90;font-size:13px;line-height:1.5}}.row{{display:flex;gap:10px;align-items:center}}</style></head><body><main><div class='muted'>ONE-WEEK PILOT</div><h1>Concierge website pilot</h1><p class='muted'>Set the inbox that should receive every completed Concierge lead, then paste the iframe into the shop website.</p><section><form method='post' action='/concierge-pilot'><label>Lead notification emails</label><input type='text' name='notification_emails' value='{emails}' placeholder='frontdesk@shop.com, owner@shop.com'><p class='muted'>Comma-separated. Up to 10 recipients.</p><label class='row'><input type='checkbox' name='enabled' value='1' {checked}> Pilot enabled</label><button type='submit'>Save pilot settings</button></form></section><section><label>Public Concierge URL</label><p><code>{html.escape(public_url)}</code></p><label>Website iframe</label><textarea readonly>{html.escape(embed)}</textarea><p class='muted'>Paste this into an HTML/embed block on the shop website. No Empty Chair dashboard is required for the pilot.</p></section></main></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@app.post("/concierge-pilot")
def save_concierge_pilot_settings(
    request: Request,
    notification_emails: str = Form(""),
    enabled: str = Form(""),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    shop_id = str(user["shop_id"])
    config = _config_for_shop(shop_id, create=True)
    emails = _normalize_emails(notification_emails)
    now = core.now_iso()
    conn = core.connect()
    try:
        _ensure_schema(conn)
        core.db_execute(
            conn,
            "UPDATE concierge_pilot_config SET notification_emails=?,enabled=?,updated_at=? WHERE shop_id=?",
            (",".join(emails), 1 if enabled == "1" else 0, now, shop_id),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/concierge-pilot", status_code=303)
