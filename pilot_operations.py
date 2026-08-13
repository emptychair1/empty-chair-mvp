"""Owner-only operational control center for a real Empty Chair pilot."""
import csv
import io
import json
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
import app as core
import fill_chairs_flow
import google_integration
import notifications
import pilot

app = core.app
FAILURE_TYPES = ("autopilot.activation_failed", "autopilot.background_failed", "calendar.availability_error", "calendar.block_failed", "offer.expiration_failed", "pilot.worker_failed", "booking.reopen_failed", "booking.confirmation_delivery_failed")

def _count(conn, query, params=()):
    row = core.db_fetchone(conn, query, params)
    return int(row["n"] or 0) if row else 0

def _snapshot(shop_id):
    conn = core.connect()
    try:
        pending = core.db_fetchall(conn, """SELECT b.id,b.amount,o.date,o.start_time,a.name AS artist_name,c.name AS customer_name FROM bookings b JOIN openings o ON o.id=b.opening_id JOIN artists a ON a.id=b.artist_id JOIN customers c ON c.id=b.customer_id WHERE o.shop_id=? AND b.status='AWAITING_CONFIRMATION' ORDER BY o.date,o.start_time""", (shop_id,))
        recent_bookings = core.db_fetchall(conn, """SELECT b.id,b.status,b.amount,o.date,o.start_time,a.name AS artist_name,c.name AS customer_name FROM bookings b JOIN openings o ON o.id=b.opening_id JOIN artists a ON a.id=b.artist_id JOIN customers c ON c.id=b.customer_id WHERE o.shop_id=? AND b.status IN ('CONFIRMED','COMPLETED','CANCELLED') ORDER BY COALESCE(b.booked_at,b.cancelled_at,o.created_at) DESC LIMIT 12""", (shop_id,))
        campaigns = pilot._campaign_rows(shop_id)
        failures = core.db_fetchall(conn, "SELECT * FROM events WHERE event_type IN (" + ",".join("?" for _ in FAILURE_TYPES) + ") ORDER BY created_at DESC LIMIT 40", FAILURE_TYPES)
        shop_failures = []
        for row in failures:
            item = dict(row)
            entity_id = item["entity_id"]
            belongs = entity_id == shop_id
            if not belongs:
                belongs = bool(core.db_fetchone(conn, "SELECT o.id FROM openings o LEFT JOIN offers f ON f.opening_id=o.id LEFT JOIN bookings b ON b.opening_id=o.id WHERE o.shop_id=? AND (o.id=? OR f.id=? OR b.id=?) LIMIT 1", (shop_id,entity_id,entity_id,entity_id)))
            if belongs: shop_failures.append(item)
        failed_deliveries = core.db_fetchall(conn, """SELECT e.created_at,e.entity_id,e.metadata,c.name AS customer_name,o.date,o.start_time FROM events e JOIN offers f ON f.id=e.entity_id JOIN openings o ON o.id=f.opening_id JOIN customers c ON c.id=f.customer_id WHERE e.event_type='offer.delivery' AND o.shop_id=? AND f.status='SENT' AND e.metadata NOT LIKE '%\"sms\": true%' AND e.metadata NOT LIKE '%\"email\": true%' ORDER BY e.created_at DESC LIMIT 20""", (shop_id,))
        confirmed = _count(conn, "SELECT COUNT(*) AS n FROM bookings b JOIN openings o ON o.id=b.opening_id WHERE o.shop_id=? AND b.status IN ('CONFIRMED','COMPLETED')", (shop_id,))
        revenue = core.db_fetchone(conn, "SELECT COALESCE(SUM(b.amount),0) AS total FROM bookings b JOIN openings o ON o.id=b.opening_id WHERE o.shop_id=? AND b.status IN ('CONFIRMED','COMPLETED')", (shop_id,))["total"]
        offers = _count(conn, "SELECT COUNT(DISTINCT e.entity_id) AS n FROM events e JOIN offers f ON f.id=e.entity_id JOIN openings o ON o.id=f.opening_id WHERE e.event_type='offer.delivery' AND o.shop_id=?", (shop_id,))
        delivered = _count(conn, """SELECT COUNT(DISTINCT e.entity_id) AS n FROM events e JOIN offers f ON f.id=e.entity_id JOIN openings o ON o.id=f.opening_id WHERE e.event_type='offer.delivery' AND o.shop_id=? AND (e.metadata LIKE '%\"sms\": true%' OR e.metadata LIKE '%\"email\": true%')""", (shop_id,))
        artists = core.db_fetchall(conn, "SELECT id,name FROM artists WHERE shop_id=? AND active=1 ORDER BY name", (shop_id,))
        calendar_health = [{"name": a["name"], "connected": google_integration.artist_calendar_connected(a["id"])} for a in artists]
    finally: conn.close()
    return {"pending":pending,"recent_bookings":recent_bookings,"campaigns":campaigns,"failures":shop_failures,"failed_deliveries":failed_deliveries,"calendar_health":calendar_health,"report":{"confirmed":confirmed,"revenue":float(revenue or 0),"offers":offers,"delivery_rate":round(delivered/offers*100,1) if offers else 0}}

@app.get("/operations", response_class=HTMLResponse)
def operations_page(request: Request, message: str=""):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT * FROM shops WHERE id=?", (user["shop_id"],))
    finally:
        conn.close()
    return core.templates.TemplateResponse(request=request,name="operations.html",context={"user":user,"shop":shop,"ops":_snapshot(user["shop_id"]),"message":message})

@app.post("/operations/campaigns/{campaign_id}/pause")
def pause_campaign(request: Request, campaign_id: str):
    return _campaign_status(request,campaign_id,"PAUSED")

@app.post("/operations/campaigns/{campaign_id}/resume")
def resume_campaign(request: Request, campaign_id: str):
    response = _campaign_status(request,campaign_id,"ACTIVE")
    user = core.get_current_user(request)
    if user: fill_chairs_flow._activate_shop(user["shop_id"])
    return response

def _campaign_status(request,campaign_id,status):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    conn=core.connect()
    try:
        row=core.db_fetchone(conn,"SELECT id FROM autopilot_campaigns WHERE id=? AND shop_id=?",(campaign_id,user["shop_id"]))
        if not row: raise HTTPException(404,"Campaign not found")
        core.db_execute(conn,"UPDATE autopilot_campaigns SET status=?,stopped_at=? WHERE id=?",(status,None if status=='ACTIVE' else core.now_iso(),campaign_id));conn.commit()
    finally: conn.close()
    core.event(f"autopilot.{status.lower()}","autopilot_campaign",campaign_id)
    return RedirectResponse("/operations",status_code=303)

@app.post("/operations/offers/{offer_id}/retry")
def retry_offer(request: Request, offer_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    conn=core.connect()
    try:
        row=core.db_fetchone(conn,"""SELECT f.id,f.status,c.*,o.date,o.start_time,o.style,o.price FROM offers f JOIN openings o ON o.id=f.opening_id JOIN customers c ON c.id=f.customer_id WHERE f.id=? AND o.shop_id=?""",(offer_id,user["shop_id"]))
    finally: conn.close()
    if not row: raise HTTPException(404,"Offer not found")
    if row["status"]!='SENT': raise HTTPException(409,"Only an active offer can be retried")
    try: notifications.send_offer_multichannel(row,row,offer_id)
    except Exception as exc:
        core.event("offer.manual_retry_failed","offer",offer_id,str(exc));return RedirectResponse("/operations?message=Retry+failed",status_code=303)
    core.event("offer.manual_retry_succeeded","offer",offer_id)
    return RedirectResponse("/operations?message=Offer+retried",status_code=303)

@app.post("/operations/bookings/{booking_id}/cancel")
def cancel_booking(request: Request, booking_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    conn=core.connect()
    try:
        row=core.db_fetchone(conn,"SELECT b.id,b.opening_id,b.status FROM bookings b JOIN openings o ON o.id=b.opening_id WHERE b.id=? AND o.shop_id=?",(booking_id,user["shop_id"]))
        if not row: raise HTTPException(404,"Booking not found")
        if row["status"] not in ('AWAITING_CONFIRMATION','CONFIRMED'): raise HTTPException(409,"Booking cannot be cancelled")
        core.db_execute(conn,"UPDATE bookings SET status='CANCELLED',cancelled_at=? WHERE id=?",(core.now_iso(),booking_id))
        core.db_execute(conn,"UPDATE openings SET status='OPEN',booking_id=NULL WHERE id=?",(row["opening_id"],))
        core.db_execute(conn,"UPDATE offers SET status='CANCELLED' WHERE opening_id=? AND status IN ('CLAIMED','SENT')",(row["opening_id"],))
        conn.commit()
    finally: conn.close()
    core.event("booking.operator_cancelled","booking",booking_id)
    try: core.start_recovery_campaign(row["opening_id"])
    except Exception as exc: core.event("booking.reopen_failed","booking",booking_id,str(exc))
    return RedirectResponse("/operations?message=Booking+cancelled+and+slot+reopened",status_code=303)

@app.get("/operations/export.csv")
def export_shop(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    conn=core.connect()
    try:
        rows=core.db_fetchall(conn,"""SELECT b.id,b.status,b.amount,b.booked_at,b.cancelled_at,o.date,o.start_time,o.end_time,a.name AS artist,c.name AS customer,c.email,c.phone FROM bookings b JOIN openings o ON o.id=b.opening_id JOIN artists a ON a.id=b.artist_id JOIN customers c ON c.id=b.customer_id WHERE o.shop_id=? ORDER BY o.date,o.start_time""",(user["shop_id"],))
    finally: conn.close()
    output=io.StringIO();fields=["id","status","amount","booked_at","cancelled_at","date","start_time","end_time","artist","customer","email","phone"];writer=csv.DictWriter(output,fieldnames=fields);writer.writeheader();writer.writerows(dict(r) for r in rows)
    return StreamingResponse(iter([output.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=empty-chair-pilot-export.csv"})
