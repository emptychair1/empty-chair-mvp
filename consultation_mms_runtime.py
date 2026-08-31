"""Inbound MMS support for Digital Consultations.

Registered before concierge_sms so this webhook handles both SMS and MMS. No DB or
network work occurs at import time. Media bytes remain at Twilio and are proxied to
authenticated shop users on demand.
"""
import base64
import html
import os
import re
import urllib.request
import uuid

from fastapi import Request
from fastapi.responses import PlainTextResponse, Response
from twilio.request_validator import RequestValidator

import app as core

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
MMS_MARKER = re.compile(r"\[\[EC_MMS:([A-Za-z0-9_-]+)\]\]")
MAX_MEDIA_BYTES = 12 * 1024 * 1024


def _normalize_phone(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _ensure_tables(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS concierge_conversations (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            lead_id TEXT,
            assigned_artist_id TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS concierge_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            body TEXT NOT NULL,
            provider_sid TEXT,
            created_at TEXT NOT NULL
        )
    """)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS consultation_media (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            media_url TEXT NOT NULL,
            content_type TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _save_message(conn, conversation_id, body, provider_sid):
    mid = f"message_{uuid.uuid4().hex[:16]}"
    now = core.now_iso()
    core.db_execute(conn, """
        INSERT INTO concierge_messages
        (id,conversation_id,direction,body,provider_sid,created_at)
        VALUES (?,?,?,?,?,?)
    """, (mid, conversation_id, "inbound", body, provider_sid or None, now))
    core.db_execute(conn, "UPDATE concierge_conversations SET updated_at=? WHERE id=?", (now, conversation_id))
    return mid


def _save_media(conn, message_id, conversation_id, media_url, content_type):
    media_id = f"media_{uuid.uuid4().hex[:18]}"
    core.db_execute(conn, """
        INSERT INTO consultation_media
        (id,message_id,conversation_id,media_url,content_type,created_at)
        VALUES (?,?,?,?,?,?)
    """, (media_id, message_id, conversation_id, media_url, content_type, core.now_iso()))
    return media_id


def _ensure_conversation(shop_id, customer_id, lead_id=None):
    conn = core.connect()
    try:
        _ensure_tables(conn)
        row = core.db_fetchone(conn, """
            SELECT id FROM concierge_conversations
            WHERE shop_id=? AND customer_id=? AND status='open'
            ORDER BY created_at DESC LIMIT 1
        """, (shop_id, customer_id))
        if row:
            return row["id"]
        cid = f"consultation_{uuid.uuid4().hex[:16]}"
        now = core.now_iso()
        core.db_execute(conn, """
            INSERT INTO concierge_conversations
            (id,shop_id,customer_id,lead_id,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?)
        """, (cid, shop_id, customer_id, lead_id, "open", now, now))
        conn.commit()
        return cid
    finally:
        conn.close()


def _twilio_request_valid(request, form):
    token = core.TWILIO_AUTH_TOKEN
    if not token:
        return False
    signature = request.headers.get("X-Twilio-Signature", "")
    public = os.getenv("EMPTY_CHAIR_BASE_URL", core.PUBLIC_BASE_URL).rstrip("/")
    url = public + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    return RequestValidator(token).validate(url, dict(form), signature)


@core.app.post("/webhooks/twilio/sms")
async def inbound_sms_or_mms(request: Request):
    form = await request.form()
    if not _twilio_request_valid(request, form):
        return PlainTextResponse("invalid signature", status_code=403)

    from_phone = str(form.get("From") or "")
    body = str(form.get("Body") or "").strip()
    sid = str(form.get("MessageSid") or "")
    try:
        num_media = max(0, min(int(str(form.get("NumMedia") or "0")), 10))
    except ValueError:
        num_media = 0
    media = []
    for i in range(num_media):
        url = str(form.get(f"MediaUrl{i}") or "").strip()
        ctype = str(form.get(f"MediaContentType{i}") or "application/octet-stream").strip()
        if url:
            media.append((url, ctype))

    # Image-only MMS has an empty Body. It is valid as long as media exists.
    if not from_phone or (not body and not media):
        return PlainTextResponse(EMPTY_TWIML, media_type="application/xml")

    conn = core.connect()
    try:
        _ensure_tables(conn)
        if sid and core.db_fetchone(conn, "SELECT id FROM concierge_messages WHERE provider_sid=?", (sid,)):
            return PlainTextResponse(EMPTY_TWIML, media_type="application/xml")
        rows = core.db_fetchall(conn, """
            SELECT c.id AS customer_id,c.shop_id,c.phone,l.id AS lead_id,x.id AS conversation_id
            FROM customers c
            LEFT JOIN concierge_leads l ON l.customer_id=c.id AND l.shop_id=c.shop_id
            LEFT JOIN concierge_conversations x ON x.customer_id=c.id AND x.shop_id=c.shop_id AND x.status='open'
            WHERE c.communication_consent=1
            ORDER BY CASE WHEN x.id IS NULL THEN 1 ELSE 0 END, x.updated_at DESC, c.updated_at DESC
        """)
        match = next((r for r in rows if _normalize_phone(r["phone"]) == _normalize_phone(from_phone)), None)
        if not match:
            return PlainTextResponse(EMPTY_TWIML, media_type="application/xml")
        consultation_id = match["conversation_id"]
        if not consultation_id:
            conn.close(); conn = None
            consultation_id = _ensure_conversation(match["shop_id"], match["customer_id"], match["lead_id"])
            conn = core.connect(); _ensure_tables(conn)

        placeholder = body or ""
        message_id = _save_message(conn, consultation_id, placeholder or "Image", sid)
        markers = []
        for media_url, content_type in media:
            media_id = _save_media(conn, message_id, consultation_id, media_url, content_type)
            markers.append(f"[[EC_MMS:{media_id}]]")
        if markers:
            stored = "\n".join(part for part in [body, *markers] if part)
            core.db_execute(conn, "UPDATE concierge_messages SET body=? WHERE id=?", (stored, message_id))
        conn.commit()
        customer_id = match["customer_id"]
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()

    summary = body[:400] if body else f"{len(media)} image attachment{'s' if len(media) != 1 else ''}"
    core.event("consultation.sms_inbound", "customer", customer_id, summary)
    if media:
        core.event("consultation.mms_inbound", "customer", customer_id, f"{len(media)} media attachment(s)")
    return PlainTextResponse(EMPTY_TWIML, media_type="application/xml")


@core.app.get("/consultations/media/{media_id}")
def consultation_media(request: Request, media_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return Response(status_code=401)
    conn = core.connect()
    try:
        row = core.db_fetchone(conn, """
            SELECT m.media_url,m.content_type
            FROM consultation_media m
            JOIN concierge_conversations x ON x.id=m.conversation_id
            WHERE m.id=? AND x.shop_id=? LIMIT 1
        """, (media_id, user["shop_id"]))
    except Exception:
        row = None
    finally:
        conn.close()
    if not row:
        return Response(status_code=404)
    content_type = str(row["content_type"] or "application/octet-stream")
    if not content_type.lower().startswith("image/"):
        return Response(status_code=415)

    media_url = str(row["media_url"])
    headers = {}
    if core.TWILIO_ACCOUNT_SID and core.TWILIO_AUTH_TOKEN:
        raw = f"{core.TWILIO_ACCOUNT_SID}:{core.TWILIO_AUTH_TOKEN}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    req = urllib.request.Request(media_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as upstream:
            data = upstream.read(MAX_MEDIA_BYTES + 1)
            actual_type = upstream.headers.get_content_type() or content_type
    except Exception:
        return Response(status_code=502)
    if len(data) > MAX_MEDIA_BYTES:
        return Response(status_code=413)
    return Response(data, media_type=actual_type, headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@core.app.middleware("http")
async def render_consultation_mms(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/consultations") or request.url.path.startswith("/consultations/media/"):
        return response
    if "text/html" not in response.headers.get("content-type", "").lower():
        return response
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    text = b"".join(chunks).decode("utf-8", errors="replace")

    def replace_marker(match):
        media_id = match.group(1)
        return (
            f"<a class='ec-mms-link' href='/consultations/media/{html.escape(media_id)}' target='_blank' rel='noopener'>"
            f"<img class='ec-mms-image' src='/consultations/media/{html.escape(media_id)}' alt='Customer reference image' loading='lazy'></a>"
        )

    text = MMS_MARKER.sub(replace_marker, text)
    if "ec-mms-image" in text and "data-ec-mms-style" not in text:
        style = "<style data-ec-mms-style>.ec-mms-image{display:block;max-width:min(100%,420px);max-height:520px;width:auto;height:auto;object-fit:contain;border:1px solid #3b4137;background:#080908;margin:8px 0 2px}.ec-mms-link{display:block;text-decoration:none}.thread .ec-mms-image{display:none}.thread .ec-mms-link:after{content:'📷 Image';color:#c7cec2}</style>"
        text = text.replace("</head>", style + "</head>", 1)
    headers = dict(response.headers); headers.pop("content-length", None)
    return Response(content=text, status_code=response.status_code, headers=headers, media_type="text/html", background=response.background)
