"""Secure, versioned quotes for Digital Consultations.

No database or network work occurs at import time. Schema creation is restricted to
quote write paths. Customer quote pages use high-entropy public tokens and never
require a customer account.
"""
import html
import secrets
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import app as core
import concierge_sms
import notifications
import stripe_deposits


def _money(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _now():
    return core.now_iso()


def _future_iso(days):
    return (datetime.now(timezone.utc) + timedelta(days=max(1, min(int(days or 7), 60)))).isoformat()


def _expired(expires_at):
    if not expires_at:
        return False
    try:
        dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt <= datetime.now(timezone.utc)
    except Exception:
        return False


def _ensure_schema(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS consultation_quotes (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            consultation_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            artist_id TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            title TEXT NOT NULL,
            project_summary TEXT NOT NULL,
            price_type TEXT NOT NULL DEFAULT 'fixed',
            amount REAL,
            min_amount REAL,
            max_amount REAL,
            deposit_amount REAL NOT NULL DEFAULT 0,
            estimated_sessions INTEGER,
            estimated_hours REAL,
            expires_at TEXT,
            public_token TEXT NOT NULL UNIQUE,
            version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            viewed_at TEXT,
            accepted_at TEXT,
            declined_at TEXT,
            superseded_at TEXT,
            deposit_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
            deposit_paid_at TEXT,
            stripe_checkout_session_id TEXT,
            stripe_payment_intent_id TEXT
        )
    """)
    conn.commit()


def _consultation(conn, consultation_id, shop_id):
    return core.db_fetchone(conn, """
        SELECT x.id,x.shop_id,x.customer_id,x.assigned_artist_id,
               c.name AS customer_name,c.phone,c.email,
               s.name AS shop_name,s.stripe_account_id,s.stripe_charges_enabled,s.stripe_payouts_enabled,
               a.name AS artist_name
        FROM concierge_conversations x
        JOIN customers c ON c.id=x.customer_id AND c.shop_id=x.shop_id
        JOIN shops s ON s.id=x.shop_id
        LEFT JOIN artists a ON a.id=x.assigned_artist_id AND a.shop_id=x.shop_id
        WHERE x.id=? AND x.shop_id=? LIMIT 1
    """, (consultation_id, shop_id))


def _quote_by_token(conn, token):
    return core.db_fetchone(conn, """
        SELECT q.*,s.name AS shop_name,s.stripe_account_id,s.stripe_charges_enabled,s.stripe_payouts_enabled,
               c.name AS customer_name,c.email AS customer_email,a.name AS artist_name
        FROM consultation_quotes q
        JOIN shops s ON s.id=q.shop_id
        JOIN customers c ON c.id=q.customer_id AND c.shop_id=q.shop_id
        LEFT JOIN artists a ON a.id=q.artist_id AND a.shop_id=q.shop_id
        WHERE q.public_token=? LIMIT 1
    """, (token,))


def _price_label(q):
    kind = str(q["price_type"] or "fixed")
    if kind == "range":
        return f"{_money(q['min_amount'])}–{_money(q['max_amount'])}"
    if kind == "hourly":
        return f"{_money(q['amount'])}/hr"
    return _money(q["amount"])


def _public_url(token):
    return f"{core.PUBLIC_BASE_URL.rstrip('/')}/q/{token}"


def _save_outbound_quote_message(consultation_id, body):
    conn = core.connect()
    try:
        concierge_sms._save_message(conn, consultation_id, "outbound", body)
        conn.commit()
    finally:
        conn.close()


def _mark_quote_paid(token, session_id):
    if not session_id or not stripe_deposits.STRIPE_SECRET_KEY:
        return False
    try:
        session = stripe_deposits._stripe_get("/checkout/sessions/" + urllib.parse.quote(session_id, safe=""))
    except Exception:
        return False
    metadata = session.get("metadata") or {}
    quote_id = metadata.get("quote_id")
    if not quote_id or session.get("payment_status") != "paid":
        return False
    conn = core.connect()
    try:
        quote = _quote_by_token(conn, token)
        if not quote or quote["id"] != quote_id:
            return False
        core.db_execute(conn, """
            UPDATE consultation_quotes
            SET deposit_status='PAID',deposit_paid_at=?,stripe_checkout_session_id=?,stripe_payment_intent_id=?
            WHERE id=?
        """, (_now(), session.get("id"), session.get("payment_intent"), quote_id))
        conn.commit()
        customer_id = quote["customer_id"]
    finally:
        conn.close()
    core.event("quote.deposit_paid", "customer", customer_id, quote_id)
    return True


def _customer_shell(title, inner):
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html.escape(title)} · Empty Chair</title><link rel='stylesheet' href='/static/style.css'>
<style>
@import url('https://fonts.googleapis.com/css2?family=Bangers&family=Inter:wght@400;600;800;900&display=swap');
*{{box-sizing:border-box}}body{{margin:0;background:#070807;color:#f2ecde;font-family:Inter,system-ui,sans-serif}}.q-wrap{{max-width:720px;margin:0 auto;padding:28px 18px 60px}}.q-brand{{display:flex;align-items:center;gap:12px;margin-bottom:28px;border-bottom:1px solid #30362d;padding-bottom:18px}}.q-brand img{{width:66px;height:66px;object-fit:contain}}.q-brand strong{{font-family:Bangers,Impact,sans-serif;font-size:30px;font-weight:400;letter-spacing:.02em}}.q-card{{border:1px solid #3a4035;background:#0d100c;box-shadow:5px 5px 0 #000;padding:24px}}.q-kicker{{color:#c7ff3e;font-size:10px;font-weight:900;letter-spacing:.14em;text-transform:uppercase}}h1{{font-family:Bangers,Impact,sans-serif;font-size:42px;font-weight:400;line-height:.95;margin:8px 0 8px}}.q-sub{{color:#9da696;font-size:13px}}.q-price{{font-family:Bangers,Impact,sans-serif;color:#c7ff3e;font-size:54px;line-height:1;margin:26px 0 6px}}.q-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:22px 0}}.q-item{{border:1px solid #2c3129;background:#090b09;padding:14px}}.q-item small{{display:block;color:#7f887a;font-size:9px;font-weight:900;letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px}}.q-summary{{white-space:pre-wrap;line-height:1.6;color:#d7d3c9;border-top:1px solid #2c3129;border-bottom:1px solid #2c3129;padding:18px 0;margin:20px 0}}.q-actions{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:22px}}button,.q-button{{min-height:52px;border:1px solid #c7ff3e;background:#c7ff3e;color:#080908;font-family:Bangers,Impact,sans-serif;font-size:22px;letter-spacing:.02em;cursor:pointer;text-decoration:none;display:flex;align-items:center;justify-content:center}}button.secondary{{background:transparent;color:#f2ecde;border-color:#4b5047}}.q-status{{padding:14px;border:1px solid #4a513f;background:#11150e;margin:18px 0;color:#dbe0d6}}.q-paid{{border-color:#c7ff3e;color:#c7ff3e}}.q-note{{color:#778071;font-size:11px;line-height:1.5;margin-top:18px}}@media(max-width:600px){{h1{{font-size:34px}}.q-price{{font-size:46px}}.q-grid,.q-actions{{grid-template-columns:1fr}}.q-card{{padding:18px}}}}
</style></head><body><main class='q-wrap'><div class='q-brand'><img src='/static/D8F5F51D-90EE-45DE-9D95-DB078BDEB87E.png?v=3' alt='Empty Chair'><strong>Secure Quote</strong></div>{inner}</main></body></html>"""


@core.app.get("/consultations/{consultation_id}/quote/new", response_class=HTMLResponse)
def new_quote_page(request: Request, consultation_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        consultation = _consultation(conn, consultation_id, user["shop_id"])
        if not consultation:
            return HTMLResponse("Consultation not found", status_code=404)
        try:
            previous = core.db_fetchone(conn, "SELECT * FROM consultation_quotes WHERE consultation_id=? ORDER BY version DESC LIMIT 1", (consultation_id,))
        except Exception:
            previous = None
    finally:
        conn.close()
    name = html.escape(str(consultation["customer_name"] or "Customer"))
    artist = html.escape(str(consultation["artist_name"] or "Shop team"))
    title = html.escape(str(previous["title"] if previous else "Tattoo project"))
    summary = html.escape(str(previous["project_summary"] if previous else ""))
    amount = html.escape(str(previous["amount"] if previous and previous["amount"] is not None else ""))
    deposit = html.escape(str(previous["deposit_amount"] if previous and previous["deposit_amount"] is not None else "100"))
    page = f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Create Quote · {name}</title><link rel='stylesheet' href='/static/style.css'><link rel='stylesheet' href='/static/consultations-brand.css?v=3'><style>body{{background:#080a08;color:#f2ecde;font-family:Inter,system-ui;margin:0}}main{{max-width:760px;margin:auto;padding:24px}}h1{{font-family:Bangers,Impact,sans-serif;font-size:42px;font-weight:400;margin:4px 0}}.ey{{color:#c7ff3e;font-size:10px;font-weight:900;letter-spacing:.13em;text-transform:uppercase}}form{{display:grid;gap:14px;margin-top:24px}}label{{display:grid;gap:7px;color:#aeb5aa;font-size:10px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}}input,textarea,select{{width:100%;background:#0d110d;color:#f2ecde;border:1px solid #3a4036;padding:13px;font:inherit}}textarea{{min-height:130px;resize:vertical}}.row{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}button{{min-height:52px;border:0;background:#c7ff3e;color:#080908;font-family:Bangers,Impact,sans-serif;font-size:22px;cursor:pointer}}a{{color:#c7ff3e;text-decoration:none}}@media(max-width:600px){{.row{{grid-template-columns:1fr}}}}</style></head><body><main><a href='/consultations/{html.escape(consultation_id)}'>← Back to consultation</a><div class='ey' style='margin-top:18px'>Digital Consultation · {artist}</div><h1>Create Secure Quote</h1><div style='color:#9ca596'>For {name}. Sending creates a versioned, secure customer link by SMS.</div><form method='post' action='/consultations/{html.escape(consultation_id)}/quote'><label>Quote title<input name='title' maxlength='120' required value='{title}'></label><label>Project summary<textarea name='project_summary' maxlength='4000' required placeholder='Describe the tattoo, size, placement, included design work, and important assumptions.'>{summary}</textarea></label><div class='row'><label>Price type<select name='price_type'><option value='fixed'>Fixed price</option><option value='range'>Price range</option><option value='hourly'>Hourly rate</option></select></label><label>Fixed price / hourly rate<input name='amount' type='number' min='0' step='0.01' value='{amount}'></label></div><div class='row'><label>Range minimum<input name='min_amount' type='number' min='0' step='0.01'></label><label>Range maximum<input name='max_amount' type='number' min='0' step='0.01'></label></div><div class='row'><label>Deposit amount<input name='deposit_amount' type='number' min='0' step='0.01' value='{deposit}'></label><label>Quote valid for<select name='expires_days'><option value='3'>3 days</option><option value='7' selected>7 days</option><option value='14'>14 days</option><option value='30'>30 days</option></select></label></div><div class='row'><label>Estimated sessions<input name='estimated_sessions' type='number' min='1' max='20'></label><label>Estimated hours<input name='estimated_hours' type='number' min='0.5' max='100' step='0.5'></label></div><button type='submit'>Send Secure Quote</button></form></main></body></html>"""
    return HTMLResponse(page, headers={"Cache-Control":"no-store"})


@core.app.post("/consultations/{consultation_id}/quote")
def create_quote(
    request: Request,
    consultation_id: str,
    title: str = Form(...),
    project_summary: str = Form(...),
    price_type: str = Form("fixed"),
    amount: str = Form(""),
    min_amount: str = Form(""),
    max_amount: str = Form(""),
    deposit_amount: str = Form("0"),
    estimated_sessions: str = Form(""),
    estimated_hours: str = Form(""),
    expires_days: int = Form(7),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    title = (title or "").strip()[:120]
    summary = (project_summary or "").strip()[:4000]
    kind = price_type if price_type in {"fixed", "range", "hourly"} else "fixed"
    try:
        amount_v = float(amount) if str(amount).strip() else None
        min_v = float(min_amount) if str(min_amount).strip() else None
        max_v = float(max_amount) if str(max_amount).strip() else None
        deposit_v = max(0.0, float(deposit_amount or 0))
        sessions_v = int(estimated_sessions) if str(estimated_sessions).strip() else None
        hours_v = float(estimated_hours) if str(estimated_hours).strip() else None
    except ValueError:
        return HTMLResponse("Quote contains an invalid number.", status_code=400)
    if not title or not summary:
        return HTMLResponse("Quote title and project summary are required.", status_code=400)
    if kind in {"fixed", "hourly"} and (amount_v is None or amount_v <= 0):
        return HTMLResponse("Enter a positive price or hourly rate.", status_code=400)
    if kind == "range" and (min_v is None or max_v is None or min_v <= 0 or max_v < min_v):
        return HTMLResponse("Enter a valid price range.", status_code=400)

    quote_id = f"quote_{uuid.uuid4().hex[:18]}"
    token = secrets.token_urlsafe(32)
    conn = core.connect()
    try:
        _ensure_schema(conn)
        consultation = _consultation(conn, consultation_id, user["shop_id"])
        if not consultation:
            return HTMLResponse("Consultation not found", status_code=404)
        latest = core.db_fetchone(conn, "SELECT MAX(version) AS v FROM consultation_quotes WHERE consultation_id=?", (consultation_id,))
        version = int(latest["v"] or 0) + 1 if latest else 1
        core.db_execute(conn, """
            UPDATE consultation_quotes SET status='superseded',superseded_at=?
            WHERE consultation_id=? AND status IN ('draft','sent','viewed','accepted') AND deposit_status<>'PAID'
        """, (_now(), consultation_id))
        deposit_status = "NOT_REQUIRED" if deposit_v <= 0 else "REQUIRED"
        core.db_execute(conn, """
            INSERT INTO consultation_quotes
            (id,shop_id,consultation_id,customer_id,artist_id,status,title,project_summary,price_type,amount,min_amount,max_amount,deposit_amount,estimated_sessions,estimated_hours,expires_at,public_token,version,created_by,created_at,deposit_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (quote_id,user["shop_id"],consultation_id,consultation["customer_id"],consultation["assigned_artist_id"],"draft",title,summary,kind,amount_v,min_v,max_v,deposit_v,sessions_v,hours_v,_future_iso(expires_days),token,version,user["id"],_now(),deposit_status))
        conn.commit()
        phone = str(consultation["phone"] or "")
        shop_name = str(consultation["shop_name"] or "the studio")
        customer_id = consultation["customer_id"]
    finally:
        conn.close()

    link = _public_url(token)
    sms = f"Your tattoo quote from {shop_name} is ready: {link} Reply here if you have questions."
    sent = notifications._send_text(phone, sms)
    conn = core.connect()
    try:
        if sent:
            core.db_execute(conn, "UPDATE consultation_quotes SET status='sent',sent_at=? WHERE id=?", (_now(), quote_id))
        conn.commit()
    finally:
        conn.close()
    if sent:
        _save_outbound_quote_message(consultation_id, sms)
        core.event("quote.sent", "customer", customer_id, quote_id)
        return RedirectResponse(f"/consultations/{consultation_id}?quote=sent", status_code=303)
    core.event("quote.send_failed", "customer", customer_id, quote_id)
    return RedirectResponse(f"/consultations/{consultation_id}?quote=send_failed", status_code=303)


@core.app.get("/q/{token}", response_class=HTMLResponse)
def public_quote(token: str, request: Request):
    session_id = request.query_params.get("session_id", "")
    if request.query_params.get("deposit") == "success" and session_id:
        _mark_quote_paid(token, session_id)
    conn = core.connect()
    try:
        try:
            q = _quote_by_token(conn, token)
        except Exception:
            q = None
        if not q:
            return HTMLResponse(_customer_shell("Quote unavailable", "<div class='q-card'><h1>Quote unavailable</h1><p>This secure quote link is invalid or no longer available.</p></div>"), status_code=404)
        if q["status"] == "sent":
            core.db_execute(conn, "UPDATE consultation_quotes SET status='viewed',viewed_at=? WHERE id=? AND status='sent'", (_now(), q["id"]))
            conn.commit()
            q = _quote_by_token(conn, token)
    finally:
        conn.close()

    status = str(q["status"])
    expired = _expired(q["expires_at"])
    if expired and status not in {"accepted","declined","superseded"} and q["deposit_status"] != "PAID":
        conn = core.connect()
        try:
            core.db_execute(conn, "UPDATE consultation_quotes SET status='expired' WHERE id=? AND status IN ('sent','viewed','draft')", (q["id"],))
            conn.commit()
        finally:
            conn.close()
        status = "expired"

    details = []
    if q["artist_name"]: details.append(("Artist", q["artist_name"]))
    if q["estimated_sessions"]: details.append(("Estimated sessions", q["estimated_sessions"]))
    if q["estimated_hours"]: details.append(("Estimated hours", q["estimated_hours"]))
    if q["deposit_amount"] and float(q["deposit_amount"]) > 0: details.append(("Deposit", _money(q["deposit_amount"])))
    details.append(("Quote version", f"v{q['version']}"))
    grid = "".join(f"<div class='q-item'><small>{html.escape(str(k))}</small><strong>{html.escape(str(v))}</strong></div>" for k,v in details)

    action = ""
    if q["deposit_status"] == "PAID":
        action = "<div class='q-status q-paid'><strong>Deposit paid.</strong> Your studio has been notified. They’ll finalize scheduling with you.</div>"
    elif status in {"superseded","expired"}:
        msg = "This quote has been replaced by a newer version." if status == "superseded" else "This quote has expired. Reply to the studio to request an updated quote."
        action = f"<div class='q-status'>{html.escape(msg)}</div>"
    elif status == "declined":
        action = "<div class='q-status'>You declined this quote. You can continue the conversation by replying to the studio’s text.</div>"
    elif status == "accepted":
        if float(q["deposit_amount"] or 0) > 0:
            if stripe_deposits.STRIPE_SECRET_KEY and q["stripe_account_id"] and q["stripe_charges_enabled"]:
                action = f"<div class='q-status'><strong>Quote accepted.</strong> Secure your project with the {_money(q['deposit_amount'])} deposit.</div><form method='post' action='/q/{html.escape(token)}/deposit'><button type='submit'>Pay Deposit Securely</button></form>"
            else:
                action = "<div class='q-status'><strong>Quote accepted.</strong> The studio will send your deposit instructions next.</div>"
        else:
            action = "<div class='q-status q-paid'><strong>Quote accepted.</strong> The studio will follow up to schedule your appointment.</div>"
    else:
        accept_label = "Accept Quote" if float(q["deposit_amount"] or 0) <= 0 else "Accept Quote"
        action = f"<div class='q-actions'><form method='post' action='/q/{html.escape(token)}/accept'><button type='submit'>{accept_label}</button></form><form method='post' action='/q/{html.escape(token)}/decline'><button class='secondary' type='submit'>Decline</button></form></div>"

    inner = f"""<section class='q-card'><div class='q-kicker'>{html.escape(str(q['shop_name']))} · Secure Quote</div><h1>{html.escape(str(q['title']))}</h1><div class='q-sub'>Prepared for {html.escape(str(q['customer_name']))}</div><div class='q-price'>{html.escape(_price_label(q))}</div><div class='q-grid'>{grid}</div><div class='q-summary'>{html.escape(str(q['project_summary']))}</div>{action}<div class='q-note'>This quote is a project estimate and does not reserve an appointment until the studio confirms scheduling. Payment is handled by Stripe; Empty Chair never receives your card details.</div></section>"""
    return HTMLResponse(_customer_shell(str(q["title"]), inner), headers={"Cache-Control":"no-store"})


@core.app.post("/q/{token}/accept")
def accept_quote(token: str):
    conn = core.connect()
    try:
        q = _quote_by_token(conn, token)
        if not q:
            return HTMLResponse("Quote not found", status_code=404)
        if q["status"] in {"superseded","expired","declined"} or _expired(q["expires_at"]):
            return RedirectResponse(f"/q/{token}", status_code=303)
        if q["deposit_status"] != "PAID":
            core.db_execute(conn, "UPDATE consultation_quotes SET status='accepted',accepted_at=? WHERE id=?", (_now(), q["id"]))
            conn.commit()
        customer_id = q["customer_id"]
    finally:
        conn.close()
    core.event("quote.accepted", "customer", customer_id, q["id"])
    return RedirectResponse(f"/q/{token}", status_code=303)


@core.app.post("/q/{token}/decline")
def decline_quote(token: str):
    conn = core.connect()
    try:
        q = _quote_by_token(conn, token)
        if not q:
            return HTMLResponse("Quote not found", status_code=404)
        if q["deposit_status"] == "PAID" or q["status"] == "superseded":
            return RedirectResponse(f"/q/{token}", status_code=303)
        core.db_execute(conn, "UPDATE consultation_quotes SET status='declined',declined_at=? WHERE id=?", (_now(), q["id"]))
        conn.commit()
        customer_id = q["customer_id"]
    finally:
        conn.close()
    core.event("quote.declined", "customer", customer_id, q["id"])
    return RedirectResponse(f"/q/{token}", status_code=303)


@core.app.post("/q/{token}/deposit")
def quote_deposit(token: str):
    conn = core.connect()
    try:
        q = _quote_by_token(conn, token)
        if not q:
            return HTMLResponse("Quote not found", status_code=404)
        if q["status"] != "accepted":
            return RedirectResponse(f"/q/{token}", status_code=303)
        if q["deposit_status"] == "PAID":
            return RedirectResponse(f"/q/{token}", status_code=303)
        deposit = float(q["deposit_amount"] or 0)
        if deposit <= 0:
            return RedirectResponse(f"/q/{token}", status_code=303)
        quote_id = q["id"]
        shop_account = q["stripe_account_id"]
        charges_enabled = q["stripe_charges_enabled"]
        customer_email = str(q["customer_email"] or "")
        shop_name = str(q["shop_name"] or "Studio")
        title = str(q["title"] or "Tattoo project")
    finally:
        conn.close()
    if not stripe_deposits.STRIPE_SECRET_KEY or not shop_account or not charges_enabled:
        return HTMLResponse("Secure deposits are not ready for this studio yet.", status_code=503)
    amount_cents = int(round(deposit * 100))
    base = core.PUBLIC_BASE_URL.rstrip("/")
    fields = {
        "mode": "payment",
        "success_url": f"{base}/q/{token}?deposit=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/q/{token}?deposit=cancelled",
        "client_reference_id": quote_id,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": stripe_deposits.STRIPE_CURRENCY,
        "line_items[0][price_data][unit_amount]": str(amount_cents),
        "line_items[0][price_data][product_data][name]": f"Tattoo deposit · {shop_name}",
        "line_items[0][price_data][product_data][description]": title,
        "metadata[quote_id]": quote_id,
        "payment_intent_data[metadata][quote_id]": quote_id,
        "payment_intent_data[transfer_data][destination]": shop_account,
        "payment_intent_data[on_behalf_of]": shop_account,
    }
    if customer_email:
        fields["customer_email"] = customer_email
    session = stripe_deposits._stripe_post("/checkout/sessions", fields, idempotency_key=f"empty-chair-quote-deposit-{quote_id}")
    conn = core.connect()
    try:
        core.db_execute(conn, "UPDATE consultation_quotes SET deposit_status='PENDING',stripe_checkout_session_id=? WHERE id=? AND deposit_status<>'PAID'", (session["id"], quote_id))
        conn.commit()
    finally:
        conn.close()
    core.event("quote.deposit_checkout_created", "quote", quote_id, session["id"])
    return RedirectResponse(session["url"], status_code=303)


@core.app.middleware("http")
async def decorate_consultation_quotes(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path.rstrip("/")
    parts = path.split("/")
    if len(parts) != 3 or parts[1] != "consultations" or request.method != "GET":
        return response
    if "text/html" not in response.headers.get("content-type", "").lower():
        return response
    consultation_id = parts[2]
    user = core.get_current_user(request)
    if not user:
        return response
    latest = None
    conn = core.connect()
    try:
        try:
            latest = core.db_fetchone(conn, "SELECT * FROM consultation_quotes WHERE consultation_id=? AND shop_id=? ORDER BY version DESC LIMIT 1", (consultation_id, user["shop_id"]))
        except Exception:
            latest = None
    finally:
        conn.close()
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    body = b"".join(chunks).decode("utf-8", errors="replace")
    cta = f"<a class='ec-quote-cta' href='/consultations/{html.escape(consultation_id)}/quote/new'>Create Quote</a>"
    if latest:
        label = f"Quote v{latest['version']} · {str(latest['status']).replace('_',' ').title()} · {_price_label(latest)}"
        card = f"<div class='ec-quote-card'><div><small>Latest secure quote</small><strong>{html.escape(label)}</strong></div>{cta}</div>"
    else:
        card = f"<div class='ec-quote-card'><div><small>Secure quoting</small><strong>Turn this consultation into a clear, trackable quote.</strong></div>{cta}</div>"
    style = "<style data-ec-quote>.ec-quote-card{display:flex;align-items:center;justify-content:space-between;gap:14px;border:1px solid #3b4137;background:#0d110d;padding:12px 14px;margin:12px 0 4px}.ec-quote-card small{display:block;color:#7f897b;font-size:9px;font-weight:900;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px}.ec-quote-card strong{color:#f2ecde;font-size:12px}.ec-quote-cta{display:flex;align-items:center;justify-content:center;min-height:40px;padding:0 14px;border:1px solid #c7ff3e;background:#c7ff3e!important;color:#080908!important;text-decoration:none!important;font-family:Bangers,Impact,sans-serif;font-size:17px;white-space:nowrap}@media(max-width:600px){.ec-quote-card{align-items:stretch;flex-direction:column}.ec-quote-cta{width:100%}}</style>"
    if "data-ec-quote" not in body:
        body = body.replace("</head>", style + "</head>", 1)
    compose_pos = body.find("<form class='consult-compose'")
    if compose_pos == -1:
        compose_pos = body.find("<form method='post' action='/consultations/")
    if compose_pos != -1:
        body = body[:compose_pos] + card + body[compose_pos:]
    headers = dict(response.headers); headers.pop("content-length", None)
    return Response(content=body, status_code=response.status_code, headers=headers, media_type="text/html", background=response.background)
