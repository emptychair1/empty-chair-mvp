"""Structured design revisions for Digital Consultations.

No database or network work occurs at import time. Schema creation happens only on
revision write paths. Customer review links use high-entropy public tokens.
"""
import html
import secrets
import uuid

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import app as core
import concierge_sms
import notifications

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _now():
    return core.now_iso()


def _ensure_schema(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS consultation_revisions (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            consultation_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            artist_id TEXT,
            version INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            artist_note TEXT NOT NULL,
            customer_note TEXT,
            public_token TEXT NOT NULL UNIQUE,
            created_by TEXT,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            viewed_at TEXT,
            approved_at TEXT,
            changes_requested_at TEXT,
            superseded_at TEXT
        )
    """)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS consultation_revision_images (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL,
            filename TEXT,
            content_type TEXT NOT NULL,
            image_data BLOB NOT NULL,
            created_at TEXT NOT NULL
        )
    """ if not core.USE_POSTGRES else """
        CREATE TABLE IF NOT EXISTS consultation_revision_images (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL,
            filename TEXT,
            content_type TEXT NOT NULL,
            image_data BYTEA NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _consultation(conn, consultation_id, shop_id):
    return core.db_fetchone(conn, """
        SELECT x.id,x.shop_id,x.customer_id,x.assigned_artist_id,
               c.name AS customer_name,c.phone,
               s.name AS shop_name,a.name AS artist_name
        FROM concierge_conversations x
        JOIN customers c ON c.id=x.customer_id AND c.shop_id=x.shop_id
        JOIN shops s ON s.id=x.shop_id
        LEFT JOIN artists a ON a.id=x.assigned_artist_id AND a.shop_id=x.shop_id
        WHERE x.id=? AND x.shop_id=? LIMIT 1
    """, (consultation_id, shop_id))


def _revision_by_token(conn, token):
    return core.db_fetchone(conn, """
        SELECT r.*,s.name AS shop_name,c.name AS customer_name,a.name AS artist_name
        FROM consultation_revisions r
        JOIN shops s ON s.id=r.shop_id
        JOIN customers c ON c.id=r.customer_id AND c.shop_id=r.shop_id
        LEFT JOIN artists a ON a.id=r.artist_id AND a.shop_id=r.shop_id
        WHERE r.public_token=? LIMIT 1
    """, (token,))


def _public_url(token):
    return f"{core.PUBLIC_BASE_URL.rstrip('/')}/revision/{token}"


def _status_label(status):
    return str(status or "").replace("_", " ").title()


def _customer_shell(title, inner):
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html.escape(title)} · Empty Chair</title><link rel='stylesheet' href='/static/style.css'>
<style>@import url('https://fonts.googleapis.com/css2?family=Bangers&family=Inter:wght@400;600;800;900&display=swap');*{{box-sizing:border-box}}body{{margin:0;background:#070807;color:#f2ecde;font-family:Inter,system-ui,sans-serif}}.rv-wrap{{max-width:760px;margin:auto;padding:26px 16px 60px}}.rv-brand{{display:flex;align-items:center;gap:12px;border-bottom:1px solid #30362d;padding-bottom:16px;margin-bottom:24px}}.rv-brand img{{width:58px;height:58px;object-fit:contain}}.rv-brand strong,h1{{font-family:Bangers,Impact,sans-serif;font-weight:400}}.rv-brand strong{{font-size:28px}}h1{{font-size:44px;line-height:.95;margin:8px 0}}.rv-card{{border:1px solid #394035;background:#0d100c;box-shadow:5px 5px 0 #000;padding:22px}}.rv-kicker{{color:#c7ff3e;font-size:10px;font-weight:900;letter-spacing:.14em;text-transform:uppercase}}.rv-image{{width:100%;max-height:620px;object-fit:contain;background:#050605;border:1px solid #30362d;margin:20px 0}}.rv-note{{white-space:pre-wrap;color:#d7d3c9;line-height:1.6;padding:16px 0;border-top:1px solid #2c3129;border-bottom:1px solid #2c3129}}.rv-status{{padding:13px;border:1px solid #4a513f;margin:16px 0;background:#11150e}}.rv-approved{{border-color:#c7ff3e;color:#c7ff3e}}.rv-actions{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:18px}}button{{min-height:52px;border:1px solid #c7ff3e;background:#c7ff3e;color:#080908;font-family:Bangers,Impact,sans-serif;font-size:22px;cursor:pointer}}button.secondary{{background:transparent;color:#f2ecde;border-color:#4b5047}}textarea{{width:100%;min-height:100px;margin-top:10px;background:#090b09;color:#f2ecde;border:1px solid #3a4036;padding:12px;font:inherit}}.rv-small{{font-size:11px;color:#818a7d;line-height:1.5;margin-top:16px}}@media(max-width:600px){{h1{{font-size:36px}}.rv-card{{padding:17px}}.rv-actions{{grid-template-columns:1fr}}}}</style></head><body><main class='rv-wrap'><div class='rv-brand'><img src='/static/D8F5F51D-90EE-45DE-9D95-DB078BDEB87E.png?v=3' alt='Empty Chair'><strong>Design Review</strong></div>{inner}</main></body></html>"""


@core.app.get("/consultations/{consultation_id}/revision/new", response_class=HTMLResponse)
def new_revision_page(request: Request, consultation_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        consultation = _consultation(conn, consultation_id, user["shop_id"])
        if not consultation:
            return HTMLResponse("Consultation not found", status_code=404)
        try:
            latest = core.db_fetchone(conn, "SELECT MAX(version) AS v FROM consultation_revisions WHERE consultation_id=? AND shop_id=?", (consultation_id, user["shop_id"]))
            next_version = int(latest["v"] or 0) + 1 if latest else 1
        except Exception:
            next_version = 1
    finally:
        conn.close()
    name = html.escape(str(consultation["customer_name"] or "Customer"))
    page = f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Revision R{next_version} · {name}</title><link rel='stylesheet' href='/static/style.css'><link rel='stylesheet' href='/static/consultations-brand.css?v=3'><style>body{{background:#080a08;color:#f2ecde;font-family:Inter,system-ui;margin:0}}main{{max-width:760px;margin:auto;padding:24px}}h1{{font-family:Bangers,Impact,sans-serif;font-size:42px;font-weight:400;margin:5px 0}}.ey{{color:#c7ff3e;font-size:10px;font-weight:900;letter-spacing:.13em;text-transform:uppercase}}form{{display:grid;gap:16px;margin-top:24px}}label{{display:grid;gap:7px;color:#aeb5aa;font-size:10px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}}textarea,input{{width:100%;background:#0d110d;color:#f2ecde;border:1px solid #3a4036;padding:13px;font:inherit}}textarea{{min-height:140px}}button{{min-height:52px;border:0;background:#c7ff3e;color:#080908;font-family:Bangers,Impact,sans-serif;font-size:22px;cursor:pointer}}a{{color:#c7ff3e;text-decoration:none}}.help{{font-size:11px;color:#7f897b;text-transform:none;letter-spacing:0;font-weight:400}}</style></head><body><main><a href='/consultations/{html.escape(consultation_id)}'>← Back to consultation</a><div class='ey' style='margin-top:18px'>Design Revision · R{next_version}</div><h1>Send Revision</h1><div style='color:#9ca596'>For {name}. The customer gets a secure review link with Approve and Request Changes.</div><form method='post' enctype='multipart/form-data' action='/consultations/{html.escape(consultation_id)}/revision'><label>Updated design image<input type='file' name='image' accept='image/jpeg,image/png,image/webp' required><span class='help'>JPEG, PNG or WebP · max 8 MB</span></label><label>Artist note<textarea name='artist_note' maxlength='4000' required placeholder='Explain what changed in this revision and anything you want the customer to review.'></textarea></label><button type='submit'>Send Revision R{next_version}</button></form></main></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control":"no-store"})


@core.app.post("/consultations/{consultation_id}/revision")
async def create_revision(request: Request, consultation_id: str, artist_note: str = Form(...), image: UploadFile = File(...)):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    note = (artist_note or "").strip()[:4000]
    if not note:
        return HTMLResponse("Revision note is required.", status_code=400)
    content_type = (image.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        return HTMLResponse("Use a JPEG, PNG, or WebP image.", status_code=400)
    data = await image.read(MAX_IMAGE_BYTES + 1)
    if not data or len(data) > MAX_IMAGE_BYTES:
        return HTMLResponse("Revision image must be between 1 byte and 8 MB.", status_code=400)

    revision_id = f"rev_{uuid.uuid4().hex[:18]}"
    image_id = f"rimg_{uuid.uuid4().hex[:18]}"
    token = secrets.token_urlsafe(32)
    conn = core.connect()
    try:
        _ensure_schema(conn)
        consultation = _consultation(conn, consultation_id, user["shop_id"])
        if not consultation:
            return HTMLResponse("Consultation not found", status_code=404)
        latest = core.db_fetchone(conn, "SELECT MAX(version) AS v FROM consultation_revisions WHERE consultation_id=? AND shop_id=?", (consultation_id, user["shop_id"]))
        version = int(latest["v"] or 0) + 1 if latest else 1
        core.db_execute(conn, "UPDATE consultation_revisions SET status='superseded',superseded_at=? WHERE consultation_id=? AND shop_id=? AND status IN ('draft','sent','viewed','approved','changes_requested')", (_now(), consultation_id, user["shop_id"]))
        core.db_execute(conn, """INSERT INTO consultation_revisions(id,shop_id,consultation_id,customer_id,artist_id,version,status,artist_note,public_token,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (revision_id,user["shop_id"],consultation_id,consultation["customer_id"],consultation["assigned_artist_id"],version,"draft",note,token,user["id"],_now()))
        core.db_execute(conn, "INSERT INTO consultation_revision_images(id,revision_id,filename,content_type,image_data,created_at) VALUES (?,?,?,?,?,?)", (image_id,revision_id,(image.filename or "revision")[:255],content_type,data,_now()))
        conn.commit()
        phone = str(consultation["phone"] or "")
        shop_name = str(consultation["shop_name"] or "the studio")
        customer_id = consultation["customer_id"]
    finally:
        conn.close()

    link = _public_url(token)
    sms = f"{shop_name} sent design revision R{version} for your tattoo. Review it here: {link} Reply here anytime with questions."
    sent = notifications._send_text(phone, sms)
    conn = core.connect()
    try:
        if sent:
            core.db_execute(conn, "UPDATE consultation_revisions SET status='sent',sent_at=? WHERE id=?", (_now(), revision_id))
        conn.commit()
    finally:
        conn.close()
    if sent:
        try:
            conn = core.connect(); concierge_sms._save_message(conn, consultation_id, "outbound", sms); conn.commit(); conn.close()
        except Exception:
            pass
        core.event("revision.sent", "customer", customer_id, revision_id)
        return RedirectResponse(f"/consultations/{consultation_id}?revision=sent", status_code=303)
    core.event("revision.send_failed", "customer", customer_id, revision_id)
    return RedirectResponse(f"/consultations/{consultation_id}?revision=send_failed", status_code=303)


@core.app.get("/revision/{token}", response_class=HTMLResponse)
def public_revision(token: str):
    conn = core.connect()
    try:
        try:
            r = _revision_by_token(conn, token)
        except Exception:
            r = None
        if not r:
            return HTMLResponse(_customer_shell("Revision unavailable", "<div class='rv-card'><h1>Revision unavailable</h1><p>This review link is invalid or no longer available.</p></div>"), status_code=404)
        if r["status"] == "sent":
            core.db_execute(conn, "UPDATE consultation_revisions SET status='viewed',viewed_at=? WHERE id=? AND status='sent'", (_now(), r["id"])); conn.commit(); r = _revision_by_token(conn, token)
    finally:
        conn.close()
    status = str(r["status"])
    if status == "approved":
        action = "<div class='rv-status rv-approved'><strong>Approved design.</strong> This revision is the current design of record.</div>"
    elif status == "changes_requested":
        note = html.escape(str(r["customer_note"] or "Changes requested"))
        action = f"<div class='rv-status'><strong>Changes requested.</strong><br>{note}</div>"
    elif status == "superseded":
        action = "<div class='rv-status'>A newer design revision has replaced this one. Use the newest review link from the studio.</div>"
    else:
        action = f"""<div class='rv-actions'><form method='post' action='/revision/{html.escape(token)}/approve'><button type='submit'>Approve Design</button></form><form method='post' action='/revision/{html.escape(token)}/changes'><textarea name='customer_note' maxlength='2000' required placeholder='What would you like changed?'></textarea><button class='secondary' type='submit'>Request Changes</button></form></div>"""
    inner = f"""<section class='rv-card'><div class='rv-kicker'>{html.escape(str(r['shop_name']))} · Revision R{r['version']}</div><h1>Design Revision R{r['version']}</h1><div style='color:#9da696;font-size:13px'>Prepared for {html.escape(str(r['customer_name']))}{' · '+html.escape(str(r['artist_name'])) if r['artist_name'] else ''}</div><img class='rv-image' src='/revision/{html.escape(token)}/image' alt='Tattoo design revision R{r['version']}'><div class='rv-note'>{html.escape(str(r['artist_note']))}</div>{action}<div class='rv-small'>Approval records this exact revision as the current design of record. Requesting changes sends your written feedback back to the studio and keeps the consultation open.</div></section>"""
    return HTMLResponse(_customer_shell(f"Revision R{r['version']}", inner), headers={"Cache-Control":"no-store"})


@core.app.get("/revision/{token}/image")
def public_revision_image(token: str):
    conn = core.connect()
    try:
        r = _revision_by_token(conn, token)
        if not r:
            return Response(status_code=404)
        img = core.db_fetchone(conn, "SELECT content_type,image_data FROM consultation_revision_images WHERE revision_id=? ORDER BY created_at LIMIT 1", (r["id"],))
    finally:
        conn.close()
    if not img:
        return Response(status_code=404)
    return Response(content=bytes(img["image_data"]), media_type=img["content_type"], headers={"Cache-Control":"private, max-age=300","X-Content-Type-Options":"nosniff"})


@core.app.post("/revision/{token}/approve")
def approve_revision(token: str):
    conn = core.connect()
    try:
        r = _revision_by_token(conn, token)
        if not r:
            return HTMLResponse("Revision not found", status_code=404)
        if r["status"] == "superseded":
            return RedirectResponse(f"/revision/{token}", status_code=303)
        core.db_execute(conn, "UPDATE consultation_revisions SET status='approved',approved_at=?,customer_note=NULL WHERE id=? AND status IN ('sent','viewed','changes_requested')", (_now(), r["id"])); conn.commit()
        consultation_id, customer_id, revision_id = r["consultation_id"], r["customer_id"], r["id"]
    finally:
        conn.close()
    core.event("revision.approved", "customer", customer_id, revision_id)
    return RedirectResponse(f"/revision/{token}", status_code=303)


@core.app.post("/revision/{token}/changes")
def request_revision_changes(token: str, customer_note: str = Form(...)):
    note = (customer_note or "").strip()[:2000]
    if not note:
        return RedirectResponse(f"/revision/{token}", status_code=303)
    conn = core.connect()
    try:
        r = _revision_by_token(conn, token)
        if not r:
            return HTMLResponse("Revision not found", status_code=404)
        if r["status"] == "superseded":
            return RedirectResponse(f"/revision/{token}", status_code=303)
        core.db_execute(conn, "UPDATE consultation_revisions SET status='changes_requested',changes_requested_at=?,customer_note=? WHERE id=? AND status IN ('sent','viewed','approved')", (_now(), note, r["id"])); conn.commit()
        consultation_id, customer_id, revision_id, version = r["consultation_id"], r["customer_id"], r["id"], r["version"]
    finally:
        conn.close()
    try:
        conn = core.connect(); concierge_sms._save_message(conn, consultation_id, "inbound", f"Revision R{version} changes requested: {note}"); conn.commit(); conn.close()
    except Exception:
        pass
    core.event("revision.changes_requested", "customer", customer_id, revision_id)
    return RedirectResponse(f"/revision/{token}", status_code=303)


@core.app.middleware("http")
async def decorate_consultation_revisions(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path.rstrip("/")
    parts = path.split("/")
    if len(parts) != 3 or parts[1] != "consultations" or request.method != "GET" or "text/html" not in response.headers.get("content-type", "").lower():
        return response
    user = core.get_current_user(request)
    if not user:
        return response
    consultation_id = parts[2]
    latest = None
    conn = core.connect()
    try:
        try:
            latest = core.db_fetchone(conn, "SELECT * FROM consultation_revisions WHERE consultation_id=? AND shop_id=? ORDER BY version DESC LIMIT 1", (consultation_id, user["shop_id"]))
        except Exception:
            latest = None
    finally:
        conn.close()
    chunks=[]
    async for chunk in response.body_iterator: chunks.append(chunk)
    body=b"".join(chunks).decode("utf-8",errors="replace")
    cta=f"<a class='ec-rev-cta' href='/consultations/{html.escape(consultation_id)}/revision/new'>Send Revision</a>"
    if latest:
        status=_status_label(latest["status"])
        approved=" · Approved design" if latest["status"]=="approved" else ""
        note = html.escape(str(latest["customer_note"] or ""))
        feedback = f"<div class='ec-rev-feedback'>{note}</div>" if note else ""
        card=f"<div class='ec-rev-card'><div><small>Design revisions</small><strong>R{latest['version']} · {html.escape(status)}{approved}</strong>{feedback}</div>{cta}</div>"
    else:
        card=f"<div class='ec-rev-card'><div><small>Design revisions</small><strong>Send a trackable design for customer approval.</strong></div>{cta}</div>"
    style="<style data-ec-revisions>.ec-rev-card{display:flex;align-items:center;justify-content:space-between;gap:14px;border:1px solid #3b4137;background:#0d110d;padding:12px 14px;margin:12px 0 4px}.ec-rev-card small{display:block;color:#7f897b;font-size:9px;font-weight:900;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px}.ec-rev-card strong{color:#f2ecde;font-size:12px}.ec-rev-feedback{font-size:11px;color:#aeb6aa;margin-top:5px}.ec-rev-cta{display:flex;align-items:center;justify-content:center;min-height:40px;padding:0 14px;border:1px solid #c7ff3e;background:#c7ff3e!important;color:#080908!important;text-decoration:none!important;font-family:Bangers,Impact,sans-serif;font-size:17px;white-space:nowrap}@media(max-width:600px){.ec-rev-card{align-items:stretch;flex-direction:column}.ec-rev-cta{width:100%}}</style>"
    if "data-ec-revisions" not in body: body=body.replace("</head>",style+"</head>",1)
    pos=body.find("<form class='consult-compose'")
    if pos==-1: pos=body.find("<form method='post' action='/consultations/")
    if pos!=-1: body=body[:pos]+card+body[pos:]
    headers=dict(response.headers); headers.pop("content-length",None)
    return Response(content=body,status_code=response.status_code,headers=headers,media_type="text/html",background=response.background)
