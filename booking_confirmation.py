"""Authenticated shop confirmation for provisional customer claims."""
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
import app as core
import google_integration
import notifications

app = core.app
app.router.routes = [r for r in app.router.routes if not (getattr(r, "path", None) == "/bookings/{booking_id}/confirm" and "POST" in (getattr(r, "methods", set()) or set()))]

def _owned_booking(conn, booking_id, shop_id):
    return core.db_fetchone(conn, """SELECT b.*, o.shop_id, o.date, o.start_time, o.end_time, s.timezone AS shop_timezone, s.name AS shop_name, a.name AS artist_name, c.name AS customer_name, c.email AS customer_email FROM bookings b JOIN openings o ON o.id=b.opening_id JOIN shops s ON s.id=o.shop_id JOIN artists a ON a.id=b.artist_id JOIN customers c ON c.id=b.customer_id WHERE b.id=? AND o.shop_id=?""", (booking_id, shop_id))

@app.post("/bookings/{booking_id}/confirm")
def confirm_booking(request: Request, booking_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    conn = core.connect()
    try:
        booking = _owned_booking(conn, booking_id, user["shop_id"])
        if not booking: raise HTTPException(404, "Booking not found")
        if booking["status"] != "AWAITING_CONFIRMATION": raise HTTPException(409, "Booking is not awaiting confirmation")
        calendar_user_id = google_integration.calendar_user_for_artist(booking["artist_id"])
        start_iso = google_integration.slot_iso(booking["date"], booking["start_time"], booking["shop_timezone"])
        end_iso = google_integration.slot_iso(booking["date"], booking["end_time"], booking["shop_timezone"])
        if calendar_user_id and google_integration.calendar_is_available_for_user(calendar_user_id, start_iso, end_iso) is False:
            raise HTTPException(409, "Artist calendar is busy. Reject this claim or resolve the conflict.")
        core.db_execute(conn, "UPDATE bookings SET status='CONFIRMED', booked_at=? WHERE id=? AND status='AWAITING_CONFIRMATION'", (core.now_iso(), booking_id))
        core.db_execute(conn, "UPDATE openings SET status='BOOKED' WHERE id=? AND status='CLAIMED'", (booking["opening_id"],))
        conn.commit()
    finally: conn.close()
    if calendar_user_id:
        try:
            result = google_integration.block_calendar_time_for_user(calendar_user_id, f"Empty Chair · {booking['customer_name']} with {booking['artist_name']}", start_iso, end_iso, booking["shop_timezone"])
            if result: core.event("calendar.slot_blocked", "booking", booking_id, result.get("id"))
        except Exception as exc: core.event("calendar.block_failed", "booking", booking_id, str(exc))
    core.event("booking.confirmed", "booking", booking_id)
    if booking["customer_email"]:
        try:
            notifications.send_email(booking["customer_email"], f"Your appointment at {booking['shop_name']} is confirmed", f"<h2>Your appointment is confirmed.</h2><p>{booking['date']} at {booking['start_time']} with {booking['artist_name']}.</p>")
        except Exception as exc: core.event("booking.confirmation_delivery_failed", "booking", booking_id, str(exc))
    return RedirectResponse("/bookings", status_code=303)

@app.post("/bookings/{booking_id}/reject")
def reject_booking(request: Request, booking_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    conn = core.connect()
    try:
        booking = _owned_booking(conn, booking_id, user["shop_id"])
        if not booking: raise HTTPException(404, "Booking not found")
        if booking["status"] != "AWAITING_CONFIRMATION": raise HTTPException(409, "Booking is not awaiting confirmation")
        core.db_execute(conn, "UPDATE bookings SET status='REJECTED' WHERE id=?", (booking_id,))
        core.db_execute(conn, "UPDATE openings SET status='OPEN', booking_id=NULL WHERE id=?", (booking["opening_id"],))
        core.db_execute(conn, "UPDATE offers SET status='REJECTED' WHERE opening_id=? AND status='CLAIMED'", (booking["opening_id"],))
        conn.commit()
    finally: conn.close()
    core.event("booking.rejected", "booking", booking_id)
    try: core.start_recovery_campaign(booking["opening_id"])
    except Exception as exc: core.event("booking.reopen_failed", "booking", booking_id, str(exc))
    return RedirectResponse("/bookings", status_code=303)
