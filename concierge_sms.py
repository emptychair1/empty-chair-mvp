"""Two-way SMS inbox for Concierge leads.

Customers keep using normal SMS. Shop users read and reply from Empty Chair.
Twilio posts inbound SMS to /webhooks/twilio/sms.
"""
import html
import os
import uuid

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from twilio.request_validator import RequestValidator

import app as core
import notifications


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
    conn.commit()


def ensure_conversation(shop_id, customer_id, lead_id=None):
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
        cid = f"conversation_{uuid.uuid4().hex[:16]}"
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


def _save_message(conn, conversation_id, direction, body, provider_sid=None):
    mid = f"message_{uuid.uuid4().hex[:16]}"
    now = core.now_iso()
    core.db_execute(conn, """
        INSERT INTO concierge_messages
        (id,conversation_id,direction,body,provider_sid,created_at)
        VALUES (?,?,?,?,?,?)
    """, (mid, conversation_id, direction, body, provider_sid, now))
    core.db_execute(conn,
        "UPDATE concierge_conversations SET updated_at=? WHERE id=?",
        (now, conversation_id))
    return mid


def _normalize_phone(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


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
async def inbound_sms(request: Request):
    form = await request.form()
    if not _twilio_request_valid(request, form):
        return PlainTextResponse("invalid signature", status_code=403)
    from_phone = str(form.get("From") or "")
    to_phone = str(form.get("To") or "")
    body = str(form.get("Body") or "").strip()
    sid = str(form.get("MessageSid") or "")
    if not from_phone or not body:
        return PlainTextResponse("", media_type="application/xml")

    conn = core.connect()
    try:
        _ensure_tables(conn)
        # A single Twilio number may serve multiple shops. Prefer an already-open
        # conversation; otherwise resolve the newest consenting matching customer.
        rows = core.db_fetchall(conn, """
            SELECT c.id AS customer_id,c.shop_id,l.id AS lead_id
            FROM customers c
            LEFT JOIN concierge_leads l ON l.customer_id=c.id AND l.shop_id=c.shop_id
            WHERE c.communication_consent=1
            ORDER BY c.updated_at DESC
        """)
        match = next((r for r in rows if _normalize_phone(r["customer_id"] and core.db_fetchone(conn,"SELECT phone FROM customers WHERE id=?",(r["customer_id"],))["phone"]) == _normalize_phone(from_phone)), None)
        if not match:
            core.event("concierge.sms_unmatched", "sms", sid or from_phone, f"from={from_phone};to={to_phone}")
            return PlainTextResponse("", media_type="application/xml")
        conversation_id = ensure_conversation(match["shop_id"], match["customer_id"], match["lead_id"])
        # ensure_conversation uses its own connection, so save after it returns.
        if sid and core.db_fetchone(conn, "SELECT id FROM concierge_messages WHERE provider_sid=?", (sid,)):
            return PlainTextResponse("", media_type="application/xml")
        _save_message(conn, conversation_id, "inbound", body, sid or None)
        conn.commit()
        core.event("concierge.sms_inbound", "customer", match["customer_id"], body[:500])
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return PlainTextResponse("<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response></Response>", media_type="application/xml")


def _conversation_for_user(conn, conversation_id, shop_id):
    return core.db_fetchone(conn, """
        SELECT x.*,c.name,c.phone,c.email,a.name AS artist_name
        FROM concierge_conversations x
        JOIN customers c ON c.id=x.customer_id AND c.shop_id=x.shop_id
        LEFT JOIN artists a ON a.id=x.assigned_artist_id AND a.shop_id=x.shop_id
        WHERE x.id=? AND x.shop_id=? LIMIT 1
    """, (conversation_id, shop_id))


@core.app.get("/messages", response_class=HTMLResponse)
def messages_inbox(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        rows = core.db_fetchall(conn, """
            SELECT x.id,x.updated_at,c.name,c.phone,
              (SELECT body FROM concierge_messages m WHERE m.conversation_id=x.id ORDER BY m.created_at DESC LIMIT 1) AS last_body
            FROM concierge_conversations x
            JOIN customers c ON c.id=x.customer_id AND c.shop_id=x.shop_id
            WHERE x.shop_id=? AND x.status='open'
            ORDER BY x.updated_at DESC
        """, (user["shop_id"],))
        cards = "".join(
            f"<a class='thread' href='/messages/{html.escape(str(r['id']))}'><strong>{html.escape(str(r['name'] or 'Customer'))}</strong><span>{html.escape(str(r['last_body'] or 'New Concierge lead'))}</span><small>{html.escape(str(r['phone'] or ''))}</small></a>"
            for r in rows
        ) or "<div class='empty'>No conversations yet.</div>"
        page = f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Messages · Empty Chair</title><link rel='stylesheet' href='/static/style.css'><style>body{{background:#080a08;color:#f0eadf;font-family:Inter,system-ui;margin:0}}main{{max-width:760px;margin:auto;padding:28px}}header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}}h1{{margin:0;font-size:38px}}a{{color:inherit;text-decoration:none}}.thread{{display:grid;gap:6px;padding:16px;border:1px solid #293027;background:#0e110e;margin-bottom:8px}}.thread strong{{font-size:17px}}.thread span{{color:#c7cec2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.thread small,.empty{{color:#7f897c}}</style></head><body><main><header><h1>Messages</h1><a href='/'>← App</a></header>{cards}</main></body></html>"""
        return HTMLResponse(page, headers={"Cache-Control":"no-store"})
    finally:
        conn.close()


@core.app.get("/messages/{conversation_id}", response_class=HTMLResponse)
def conversation_page(request: Request, conversation_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        convo = _conversation_for_user(conn, conversation_id, user["shop_id"])
        if not convo:
            return HTMLResponse("Conversation not found", status_code=404)
        rows = core.db_fetchall(conn, "SELECT * FROM concierge_messages WHERE conversation_id=? ORDER BY created_at", (conversation_id,))
        bubbles = "".join(f"<div class='msg {html.escape(str(r['direction']))}'><div>{html.escape(str(r['body'] or ''))}</div><small>{html.escape(str(r['created_at'] or ''))}</small></div>" for r in rows)
        name = html.escape(str(convo["name"] or "Customer"))
        page = f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>{name} · Messages</title><link rel='stylesheet' href='/static/style.css'><style>body{{background:#080a08;color:#f0eadf;font-family:Inter,system-ui;margin:0}}main{{max-width:760px;margin:auto;padding:20px}}header{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #293027;padding-bottom:14px}}header h1{{font-size:22px;margin:0}}a{{color:#d8ff45;text-decoration:none}}.chat{{display:flex;flex-direction:column;gap:10px;padding:20px 0;min-height:55vh}}.msg{{max-width:78%;padding:11px 13px;border-radius:14px;background:#1a1f19}}.msg.outbound{{align-self:flex-end;background:#d8ff45;color:#10130f}}.msg small{{display:block;opacity:.6;font-size:9px;margin-top:5px}}form{{display:flex;gap:8px;position:sticky;bottom:0;background:#080a08;padding:12px 0}}textarea{{flex:1;min-height:48px;resize:vertical;background:#111511;color:#fff;border:1px solid #343c32;padding:12px;font:inherit}}button{{border:0;background:#d8ff45;color:#10130f;font-weight:900;padding:0 18px}}</style></head><body><main><header><div><h1>{name}</h1><small>{html.escape(str(convo['phone'] or ''))}</small></div><a href='/messages'>← Inbox</a></header><section class='chat'>{bubbles}</section><form method='post' action='/messages/{html.escape(conversation_id)}/send'><textarea name='body' maxlength='1500' required placeholder='Text {name}…'></textarea><button type='submit'>Send</button></form></main></body></html>"""
        return HTMLResponse(page, headers={"Cache-Control":"no-store"})
    finally:
        conn.close()


@core.app.post("/messages/{conversation_id}/send")
def send_message(request: Request, conversation_id: str, body: str = Form(...)):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    text = (body or "").strip()
    if not text:
        return RedirectResponse(f"/messages/{conversation_id}", status_code=303)
    conn = core.connect()
    try:
        _ensure_tables(conn)
        convo = _conversation_for_user(conn, conversation_id, user["shop_id"])
        if not convo:
            return HTMLResponse("Conversation not found", status_code=404)
        if not notifications._send_text(convo["phone"], text):
            return HTMLResponse("SMS could not be sent. Check Twilio/SMS configuration.", status_code=503)
        _save_message(conn, conversation_id, "outbound", text)
        conn.commit()
        core.event("concierge.sms_outbound", "customer", convo["customer_id"], text[:500])
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return RedirectResponse(f"/messages/{conversation_id}", status_code=303)
