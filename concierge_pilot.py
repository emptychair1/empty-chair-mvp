"""One-week Concierge pilot: compact iframe chat, notification emails, and automatic lead handoff."""

import html
import json
import secrets

import resend
from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core

app = core.app


def _ensure_schema(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS concierge_pilot_config (
            shop_id TEXT PRIMARY KEY,
            public_token TEXT NOT NULL UNIQUE,
            notification_emails TEXT NOT NULL DEFAULT '',
            display_name TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    try:
        core.db_execute(conn, "ALTER TABLE concierge_pilot_config ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
    except Exception:
        conn.rollback()
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
            "INSERT INTO concierge_pilot_config(shop_id,public_token,notification_emails,display_name,enabled,created_at,updated_at) VALUES (?,?,?,?,1,?,?)",
            (shop_id, token, "", "", now, now),
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


def _pilot_name(shop_id: str):
    config = _config_for_shop(shop_id, create=False) or {}
    value = str(config.get("display_name") or "").strip()
    return value or "Tattoo Shop"


def _recipients_for_shop(shop_id: str):
    config = _config_for_shop(shop_id, create=False)
    if not config or not int(config.get("enabled") or 0):
        return []
    recipients = _normalize_emails(config.get("notification_emails") or "")
    if recipients:
        return recipients

    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT email FROM shops WHERE id=?", (shop_id,))
        if shop and core.normalize_email(shop["email"]):
            recipients.append(core.normalize_email(shop["email"]))
        users = core.db_fetchall(
            conn,
            "SELECT email FROM users WHERE shop_id=? AND is_active=1 ORDER BY created_at",
            (shop_id,),
        )
        for user in users:
            email = core.normalize_email(user["email"])
            if email and email not in recipients:
                recipients.append(email)
    finally:
        conn.close()
    return recipients[:10]


def _send_live_email(to_email: str, subject: str, body: str):
    to_email = core.normalize_email(to_email)
    if not to_email:
        return False, "recipient missing"
    if not core.RESEND_API_KEY:
        return False, "RESEND_API_KEY missing"
    if not core.EMAIL_FROM:
        return False, "EMPTY_CHAIR_EMAIL_FROM missing"

    try:
        resend.api_key = core.RESEND_API_KEY
        response = resend.Emails.send({
            "from": core.EMAIL_FROM,
            "to": [to_email],
            "subject": subject,
            "html": body,
        })
        return True, str(response)
    except Exception as exc:
        return False, str(exc)


def send_new_lead_email(shop_id: str, profile: dict, confidence: int, customer_id: str = ""):
    recipients = _recipients_for_shop(shop_id)
    if not recipients:
        core.event("concierge.lead_email_skipped", "customer", customer_id or shop_id, "no recipients")
        return False

    shop_name = _pilot_name(shop_id)
    def e(value): return html.escape(str(value or "Not specified"))
    consent = "YES" if profile.get("offer_opt_in") else "NO"
    subject = f"New Concierge lead for {shop_name}: {profile.get('name') or 'New lead'}"
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;line-height:1.55;color:#171917">
      <div style="font-size:12px;letter-spacing:.08em;color:#697066">EMPTY CHAIR CONCIERGE</div>
      <h2>New lead for {e(shop_name)}</h2>
      <table style="width:100%;border-collapse:collapse">
        <tr><td>Name</td><td><strong>{e(profile.get('name'))}</strong></td></tr>
        <tr><td>Phone</td><td>{e(profile.get('phone'))}</td></tr>
        <tr><td>Email</td><td>{e(profile.get('email'))}</td></tr>
        <tr><td>Project</td><td>{e(profile.get('project'))}</td></tr>
        <tr><td>Style</td><td>{e(profile.get('styles'))}</td></tr>
        <tr><td>Placement</td><td>{e(profile.get('placement'))}</td></tr>
        <tr><td>Budget</td><td>{e(profile.get('budget'))}</td></tr>
        <tr><td>Timing</td><td>{e(profile.get('timing'))}</td></tr>
        <tr><td>Artist / vibe</td><td>{e(profile.get('artist_vibe'))}</td></tr>
        <tr><td>Preferred contact</td><td>{e(profile.get('contact_preference'))}</td></tr>
        <tr><td>Contact permission</td><td><strong>{consent}</strong></td></tr>
      </table>
    </div>
    """

    any_sent = False
    for recipient in recipients:
        core.event("concierge.lead_email_attempt", "customer", customer_id or shop_id, json.dumps({"recipient": recipient}))
        sent, detail = _send_live_email(recipient, subject, body)
        if sent:
            any_sent = True
            core.event("concierge.lead_emailed", "customer", customer_id or shop_id, json.dumps({"recipient": recipient, "provider": "resend", "response": detail[:500]}))
        else:
            core.event("concierge.lead_email_failed", "customer", customer_id or shop_id, json.dumps({"recipient": recipient, "error": detail[:500]}))
    return any_sent


def _render_widget(shop_id: str):
    with open("templates/concierge_widget.html", "r", encoding="utf-8") as handle:
        page = handle.read()
    page = page.replace("{{ shop_id|tojson }}", json.dumps(shop_id))
    return HTMLResponse(page, headers={"Cache-Control": "no-store", "Content-Security-Policy": "frame-ancestors *"})


@app.get("/c/{token}", response_class=HTMLResponse)
def concierge_public_embed(token: str):
    shop_id = shop_for_public_token(token)
    if not shop_id:
        return HTMLResponse("<h1>Concierge link is inactive.</h1>", status_code=404)
    return _render_widget(shop_id)


@app.get("/concierge-pilot", response_class=HTMLResponse)
def concierge_pilot_settings(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    config = _config_for_shop(str(user["shop_id"]), create=True)
    public_url = f"{core.PUBLIC_BASE_URL.rstrip('/')}/c/{config['public_token']}"
    pilot_name = str(config.get("display_name") or "")
    iframe_title = f"{pilot_name} Tattoo Concierge" if pilot_name else "Tattoo Concierge"
    embed = f'<iframe src="{public_url}" title="{html.escape(iframe_title)}" style="width:100%;max-width:420px;height:620px;border:0" loading="lazy"></iframe>'
    emails = html.escape(config.get("notification_emails") or "")
    display_name = html.escape(pilot_name)
    checked = "checked" if int(config.get("enabled") or 0) else ""
    status = html.escape(request.query_params.get("email_test") or "")
    status_html = f"<p style='color:#d8ff45'><strong>{status}</strong></p>" if status else ""

    page = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Concierge Pilot</title><style>body{{background:#080908;color:#f2eee5;font-family:Inter,system-ui;margin:0}}main{{max-width:850px;margin:auto;padding:28px}}section{{border:1px solid #2b3029;background:#0e110e;padding:22px;margin:14px 0}}label{{display:block;margin:14px 0 6px;font-weight:700}}input[type=text],textarea{{width:100%;box-sizing:border-box;background:#080a08;color:#f2eee5;border:1px solid #384036;padding:12px;font-size:16px}}textarea{{min-height:120px}}button{{background:#b7ff3c;color:#0b0e09;border:0;padding:12px 16px;font-weight:900;cursor:pointer}}code{{word-break:break-all;color:#dfffb0}}.muted{{color:#929a90;font-size:13px}}</style></head><body><main><h1>Concierge website pilot</h1><p class='muted'>Set the client shop name and the inbox that should receive completed Concierge leads.</p>{status_html}<section><form method='post' action='/concierge-pilot'><label>Client shop name</label><input type='text' name='display_name' value='{display_name}' placeholder='Blind Wolf Tattoo'><label>Lead notification emails</label><input type='text' name='notification_emails' value='{emails}' placeholder='frontdesk@shop.com, owner@shop.com'><label><input type='checkbox' name='enabled' value='1' {checked}> Pilot enabled</label><br><br><button type='submit'>Save pilot settings</button></form><form method='post' action='/concierge-pilot/test-email' style='margin-top:14px'><button type='submit'>Send test lead email</button></form></section><section><label>Public Concierge URL</label><p><code>{html.escape(public_url)}</code></p><label>Website iframe</label><textarea readonly>{html.escape(embed)}</textarea></section></main></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@app.post("/concierge-pilot")
def save_concierge_pilot_settings(request: Request, display_name: str = Form(""), notification_emails: str = Form(""), enabled: str = Form("")):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    shop_id = str(user["shop_id"])
    _config_for_shop(shop_id, create=True)
    emails = _normalize_emails(notification_emails)
    clean_name = (display_name or "").strip()[:120]
    conn = core.connect()
    try:
        _ensure_schema(conn)
        core.db_execute(
            conn,
            "UPDATE concierge_pilot_config SET display_name=?,notification_emails=?,enabled=?,updated_at=? WHERE shop_id=?",
            (clean_name, ",".join(emails), 1 if enabled == "1" else 0, core.now_iso(), shop_id),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/concierge-pilot", status_code=303)


@app.post("/concierge-pilot/test-email")
def test_concierge_pilot_email(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    shop_id = str(user["shop_id"])
    recipients = _recipients_for_shop(shop_id)
    if not recipients:
        return RedirectResponse("/concierge-pilot?email_test=No+recipient+email+is+configured", status_code=303)

    shop_name = _pilot_name(shop_id)
    sent_count = 0
    last_error = ""
    body = f"<div style='font-family:Arial,sans-serif'><h2>{html.escape(shop_name)} Concierge test</h2><p>If you received this, Concierge lead delivery is working.</p></div>"
    for recipient in recipients:
        sent, detail = _send_live_email(recipient, f"{shop_name} Concierge test lead", body)
        if sent:
            sent_count += 1
        else:
            last_error = detail

    if sent_count:
        return RedirectResponse(f"/concierge-pilot?email_test=Test+email+sent+to+{sent_count}+recipient(s)", status_code=303)
    safe_error = last_error.replace(" ", "+")[:180]
    return RedirectResponse(f"/concierge-pilot?email_test=Send+failed:+{safe_error}", status_code=303)
