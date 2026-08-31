"""Post-payment scheduling for consultation quotes.

Founder/demo simulation is explicitly gated and never calls Stripe. Real and simulated
paid quotes feed the same scheduling path. No DB or network work occurs at import time.
"""
import html
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import app as core
import concierge_sms
import google_integration
import notifications
from founder_simulation_safety import FounderSimulationSafetyError, load_and_assert_founder_simulation_target

PAID_STATES = {"PAID", "SIMULATED_PAID"}


def _simulation_allowed(user):
    if getattr(core, "DEMO_MODE", False):
        return True
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, user["shop_id"])
        return True
    except FounderSimulationSafetyError:
        return False
    except Exception:
        return False
    finally:
        conn.close()


def _ensure_table(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS consultation_quote_scheduling (
            quote_id TEXT PRIMARY KEY,
            booking_id TEXT,
            simulation_used INTEGER NOT NULL DEFAULT 0,
            simulated_by TEXT,
            simulated_at TEXT,
            scheduled_by TEXT,
            scheduled_at TEXT
        )
    """)
    conn.commit()


def _quote(conn, quote_id, shop_id):
    return core.db_fetchone(conn, """
        SELECT q.*,x.customer_id AS conversation_customer_id,c.name AS customer_name,c.phone AS customer_phone,
               c.email AS customer_email,s.name AS shop_name,s.timezone AS shop_timezone,
               x.assigned_artist_id
        FROM consultation_quotes q
        JOIN concierge_conversations x ON x.id=q.consultation_id AND x.shop_id=q.shop_id
        JOIN customers c ON c.id=q.customer_id AND c.shop_id=q.shop_id
        JOIN shops s ON s.id=q.shop_id
        WHERE q.id=? AND q.shop_id=? LIMIT 1
    """, (quote_id, shop_id))


def _latest_quote(conn, consultation_id, shop_id):
    try:
        return core.db_fetchone(conn, "SELECT * FROM consultation_quotes WHERE consultation_id=? AND shop_id=? ORDER BY version DESC LIMIT 1", (consultation_id, shop_id))
    except Exception:
        return None


def _booking_amount(q):
    kind = str(q["price_type"] or "fixed")
    if kind == "range":
        return float(q["max_amount"] or q["min_amount"] or 0)
    if kind == "hourly":
        rate = float(q["amount"] or 0)
        hours = float(q["estimated_hours"] or 1)
        return rate * hours
    return float(q["amount"] or 0)


def _save_consultation_message(consultation_id, body):
    conn = core.connect()
    try:
        concierge_sms._save_message(conn, consultation_id, "outbound", body)
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()


def _page(title, inner):
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{html.escape(title)} · Empty Chair</title><link rel='stylesheet' href='/static/style.css'><link rel='stylesheet' href='/static/consultations-brand.css?v=3'>
<style>@import url('https://fonts.googleapis.com/css2?family=Bangers&family=Inter:wght@400;600;800;900&display=swap');*{{box-sizing:border-box}}body{{margin:0;background:#070807;color:#f2ecde;font-family:Inter,system-ui}}main{{max-width:760px;margin:auto;padding:28px 18px 60px}}h1{{font-family:Bangers,Impact,sans-serif;font-size:44px;font-weight:400;line-height:1;margin:8px 0}}.ey{{color:#c7ff3e;font-size:10px;font-weight:900;letter-spacing:.13em;text-transform:uppercase}}.card{{border:1px solid #3a4035;background:#0d100c;box-shadow:5px 5px 0 #000;padding:22px;margin-top:20px}}form{{display:grid;gap:14px}}label{{display:grid;gap:7px;color:#aeb5aa;font-size:10px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}}input,select{{width:100%;background:#090b09;color:#f2ecde;border:1px solid #3a4036;padding:13px;font:inherit}}.row{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}button,.btn{{min-height:50px;border:1px solid #c7ff3e;background:#c7ff3e;color:#080908;font-family:Bangers,Impact,sans-serif;font-size:21px;text-decoration:none;display:flex;align-items:center;justify-content:center;cursor:pointer}}a{{color:#c7ff3e;text-decoration:none}}.note{{color:#899184;font-size:12px;line-height:1.5}}@media(max-width:620px){{.row{{grid-template-columns:1fr}}h1{{font-size:36px}}}}</style></head><body><main>{inner}</main></body></html>"""


@core.app.post("/consultations/quotes/{quote_id}/simulate-deposit-paid")
def simulate_quote_deposit_paid(request: Request, quote_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    if not _simulation_allowed(user):
        raise HTTPException(403, "Deposit simulation is restricted to founder/demo testing.")
    conn = core.connect()
    try:
        _ensure_table(conn)
        q = _quote(conn, quote_id, user["shop_id"])
        if not q:
            raise HTTPException(404, "Quote not found")
        if q["status"] != "accepted":
            raise HTTPException(409, "Only an accepted quote can simulate a paid deposit.")
        if str(q["deposit_status"]) == "PAID":
            return RedirectResponse(f"/consultations/{q['consultation_id']}?deposit=already_paid", status_code=303)
        now = core.now_iso()
        core.db_execute(conn, "UPDATE consultation_quotes SET deposit_status='SIMULATED_PAID',deposit_paid_at=? WHERE id=?", (now, quote_id))
        core.db_execute(conn, "DELETE FROM consultation_quote_scheduling WHERE quote_id=?", (quote_id,))
        core.db_execute(conn, "INSERT INTO consultation_quote_scheduling(quote_id,simulation_used,simulated_by,simulated_at) VALUES (?,?,?,?)", (quote_id, 1, user["id"], now))
        conn.commit()
        consultation_id = q["consultation_id"]
    except Exception:
        try: conn.rollback()
        except Exception: pass
        raise
    finally:
        conn.close()
    core.event("quote.deposit_simulated", "quote", quote_id, f"user={user['id']}")
    return RedirectResponse(f"/consultations/{consultation_id}?deposit=simulated", status_code=303)


@core.app.get("/consultations/quotes/{quote_id}/schedule", response_class=HTMLResponse)
def quote_schedule_page(request: Request, quote_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_table(conn)
        q = _quote(conn, quote_id, user["shop_id"])
        if not q:
            return HTMLResponse("Quote not found", status_code=404)
        if str(q["deposit_status"]) not in PAID_STATES:
            return HTMLResponse("Deposit must be paid before scheduling.", status_code=409)
        existing = core.db_fetchone(conn, "SELECT booking_id FROM consultation_quote_scheduling WHERE quote_id=?", (quote_id,))
        if existing and existing["booking_id"]:
            return RedirectResponse(f"/booking/{existing['booking_id']}", status_code=303)
        artists = core.db_fetchall(conn, "SELECT id,name FROM artists WHERE shop_id=? AND active=1 ORDER BY name", (user["shop_id"],))
    finally:
        conn.close()
    selected = str(q["assigned_artist_id"] or q["artist_id"] or "")
    options = "".join(f"<option value='{html.escape(str(a['id']))}'{' selected' if str(a['id'])==selected else ''}>{html.escape(str(a['name']))}</option>" for a in artists)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    inner = f"""<a href='/consultations/{html.escape(str(q['consultation_id']))}'>← Back to consultation</a><div class='ey' style='margin-top:18px'>Deposit received · Ready to book</div><h1>Schedule Appointment</h1><div class='note'>{html.escape(str(q['customer_name']))} · {html.escape(str(q['title']))}. Empty Chair will check the artist's connected Google Calendar before confirming.</div><section class='card'><form method='post' action='/consultations/quotes/{html.escape(quote_id)}/schedule'><label>Artist<select name='artist_id' required>{options}</select></label><div class='row'><label>Date<input type='date' name='date' min='{tomorrow}' required></label><label>Start time<input type='time' name='start_time' required></label></div><label>End time<input type='time' name='end_time' required></label><button type='submit'>Confirm Appointment</button><div class='note'>For simulated deposits, the booking remains visibly marked SIMULATED_PAID. Real Stripe payments remain PAID.</div></form></section>"""
    return HTMLResponse(_page("Schedule Appointment", inner), headers={"Cache-Control":"no-store"})


@core.app.post("/consultations/quotes/{quote_id}/schedule")
def schedule_paid_quote(request: Request, quote_id: str, artist_id: str = Form(...), date: str = Form(...), start_time: str = Form(...), end_time: str = Form(...)):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    if not date or not start_time or not end_time or end_time <= start_time:
        return HTMLResponse(_page("Invalid time", "<section class='card'><h1>Check the appointment time</h1><p>End time must be after start time.</p></section>"), status_code=400)
    conn = core.connect()
    try:
        _ensure_table(conn)
        q = _quote(conn, quote_id, user["shop_id"])
        if not q:
            raise HTTPException(404, "Quote not found")
        if str(q["deposit_status"]) not in PAID_STATES:
            raise HTTPException(409, "Deposit must be paid before scheduling")
        existing = core.db_fetchone(conn, "SELECT booking_id FROM consultation_quote_scheduling WHERE quote_id=?", (quote_id,))
        if existing and existing["booking_id"]:
            return RedirectResponse(f"/booking/{existing['booking_id']}", status_code=303)
        artist = core.db_fetchone(conn, "SELECT id,name FROM artists WHERE id=? AND shop_id=? AND active=1", (artist_id, user["shop_id"]))
        if not artist:
            raise HTTPException(404, "Artist not found")
        timezone_name = str(q["shop_timezone"] or "America/New_York")
    finally:
        conn.close()

    start_iso = google_integration.slot_iso(date, start_time, timezone_name)
    end_iso = google_integration.slot_iso(date, end_time, timezone_name)
    calendar_user = google_integration.calendar_user_for_artist(artist_id)
    if calendar_user:
        try:
            available = google_integration.calendar_is_available_for_user(calendar_user, start_iso, end_iso)
        except Exception as exc:
            core.event("quote.schedule_calendar_check_failed", "quote", quote_id, str(exc))
            available = None
        if available is False:
            return HTMLResponse(_page("Time unavailable", f"<section class='card'><div class='ey'>Calendar conflict</div><h1>That time is busy</h1><p>{html.escape(str(artist['name']))}'s Google Calendar already has something in that slot.</p><a class='btn' href='/consultations/quotes/{html.escape(quote_id)}/schedule'>Choose Another Time</a></section>"), status_code=409)

    opening_id = f"opening_{uuid.uuid4().hex[:12]}"
    booking_id = f"booking_{uuid.uuid4().hex[:12]}"
    now = core.now_iso()
    expires = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    amount = _booking_amount(q)
    deposit_status = str(q["deposit_status"])
    conn = core.connect()
    try:
        _ensure_table(conn)
        # Recheck idempotency after the external calendar check.
        existing = core.db_fetchone(conn, "SELECT booking_id FROM consultation_quote_scheduling WHERE quote_id=?", (quote_id,))
        if existing and existing["booking_id"]:
            conn.rollback()
            return RedirectResponse(f"/booking/{existing['booking_id']}", status_code=303)
        core.db_execute(conn, "INSERT INTO openings(id,shop_id,artist_id,date,start_time,end_time,service,style,price,status,created_at,expires_at,booking_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (opening_id,user["shop_id"],artist_id,date,start_time,end_time,"tattoo",None,amount,"BOOKED",now,expires,booking_id))
        core.db_execute(conn, "INSERT INTO bookings(id,opening_id,customer_id,artist_id,booking_url,status,amount,deposit_amount,deposit_status,deposit_paid_at,booked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (booking_id,opening_id,q["customer_id"],artist_id,None,"CONFIRMED",amount,float(q["deposit_amount"] or 0),deposit_status,q["deposit_paid_at"],now))
        cursor = core.db_execute(conn, "UPDATE consultation_quote_scheduling SET booking_id=?,scheduled_by=?,scheduled_at=? WHERE quote_id=? AND booking_id IS NULL", (booking_id,user["id"],now,quote_id))
        if cursor.rowcount != 1:
            core.db_execute(conn, "INSERT INTO consultation_quote_scheduling(quote_id,booking_id,simulation_used,scheduled_by,scheduled_at) VALUES (?,?,?,?,?)", (quote_id,booking_id,1 if deposit_status=="SIMULATED_PAID" else 0,user["id"],now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if calendar_user:
        try:
            event = google_integration.block_calendar_time_for_user(calendar_user, f"Empty Chair · {q['customer_name']} with {artist['name']}", start_iso, end_iso, timezone_name)
            if event and event.get("id"):
                google_integration.remember_booking_event(booking_id, calendar_user, event["id"])
                core.event("calendar.slot_blocked", "booking", booking_id, event["id"])
        except Exception as exc:
            core.event("calendar.block_failed", "booking", booking_id, str(exc))

    message = f"You're booked with {artist['name']} at {q['shop_name']} on {date} at {start_time}. Your deposit is recorded. Reply here if you need anything before the appointment."
    try:
        if q["customer_phone"] and notifications._send_text(str(q["customer_phone"]), message):
            _save_consultation_message(str(q["consultation_id"]), message)
    except Exception as exc:
        core.event("quote.schedule_sms_failed", "booking", booking_id, str(exc))
    core.event("quote.scheduled", "booking", booking_id, f"quote={quote_id};deposit={deposit_status}")
    return RedirectResponse(f"/consultations/{q['consultation_id']}?booking=confirmed", status_code=303)


@core.app.middleware("http")
async def decorate_post_payment_actions(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path.rstrip("/")
    parts = path.split("/")
    if request.method != "GET" or len(parts) != 3 or parts[1] != "consultations" or "text/html" not in response.headers.get("content-type", "").lower():
        return response
    user = core.get_current_user(request)
    if not user:
        return response
    consultation_id = parts[2]
    conn = core.connect()
    try:
        latest = _latest_quote(conn, consultation_id, user["shop_id"])
        scheduling = None
        booking = None
        if latest:
            try:
                scheduling = core.db_fetchone(conn, "SELECT * FROM consultation_quote_scheduling WHERE quote_id=?", (latest["id"],))
                if scheduling and scheduling["booking_id"]:
                    booking = core.db_fetchone(conn, "SELECT b.id,o.date,o.start_time,a.name AS artist_name FROM bookings b JOIN openings o ON o.id=b.opening_id JOIN artists a ON a.id=b.artist_id WHERE b.id=?", (scheduling["booking_id"],))
            except Exception:
                pass
    finally:
        conn.close()
    if not latest:
        return response
    chunks=[]
    async for chunk in response.body_iterator: chunks.append(chunk)
    body=b"".join(chunks).decode("utf-8",errors="replace")
    card=""
    if booking:
        card=f"<div class='ec-postpay'><div><small>Booked</small><strong>{html.escape(str(booking['date']))} at {html.escape(str(booking['start_time']))} · {html.escape(str(booking['artist_name']))}</strong></div><a href='/booking/{html.escape(str(booking['id']))}'>View Booking</a></div>"
    elif str(latest["deposit_status"]) in PAID_STATES:
        label="Test deposit recorded" if str(latest["deposit_status"])=="SIMULATED_PAID" else "Deposit paid"
        card=f"<div class='ec-postpay'><div><small>{label}</small><strong>Ready to choose an appointment time.</strong></div><a href='/consultations/quotes/{html.escape(str(latest['id']))}/schedule'>Schedule Appointment</a></div>"
    elif str(latest["status"])=="accepted" and float(latest["deposit_amount"] or 0)>0 and _simulation_allowed(user):
        card=f"<div class='ec-postpay ec-test'><div><small>Founder / demo testing</small><strong>Stripe blocked? Simulate the paid state without recording a real payment.</strong></div><form method='post' action='/consultations/quotes/{html.escape(str(latest['id']))}/simulate-deposit-paid'><button type='submit'>Simulate Deposit Paid</button></form></div>"
    if card:
        style="<style data-ec-postpay>.ec-postpay{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid #c7ff3e;background:#10140d;padding:13px 14px;margin:10px 0}.ec-postpay.ec-test{border-style:dashed}.ec-postpay small{display:block;color:#c7ff3e;font-size:9px;font-weight:900;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px}.ec-postpay strong{font-size:12px;color:#f2ecde}.ec-postpay a,.ec-postpay button{min-height:40px;padding:0 13px;border:1px solid #c7ff3e;background:#c7ff3e;color:#080908!important;text-decoration:none;font-family:Bangers,Impact,sans-serif;font-size:17px;display:flex;align-items:center;justify-content:center;cursor:pointer;white-space:nowrap}@media(max-width:600px){.ec-postpay{align-items:stretch;flex-direction:column}.ec-postpay a,.ec-postpay button{width:100%}}</style>"
        if "data-ec-postpay" not in body: body=body.replace("</head>",style+"</head>",1)
        pos=body.find("<form class='consult-compose'")
        if pos==-1: pos=body.find("<form method='post' action='/consultations/")
        if pos!=-1: body=body[:pos]+card+body[pos:]
    headers=dict(response.headers); headers.pop("content-length",None)
    return Response(content=body,status_code=response.status_code,headers=headers,media_type="text/html",background=response.background)
