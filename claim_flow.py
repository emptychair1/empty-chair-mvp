"""Atomic public customer claim flow for Empty Chair."""
import uuid
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
import app as core
import google_integration

app = core.app


def remove_route(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes = [route for route in app.router.routes if not (getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()))]

remove_route("/offer/{offer_id}/claim", "POST")


@app.post("/offer/{offer_id}/claim")
def claim_offer_atomic(offer_id: str):
    conn = core.connect()
    try:
        offer = core.db_fetchone(conn, """SELECT o.*, op.status AS opening_status, op.shop_id, op.artist_id, op.price, op.date, op.start_time, op.end_time, a.name AS artist_name, c.name AS customer_name, s.timezone AS shop_timezone FROM offers o JOIN openings op ON op.id=o.opening_id JOIN artists a ON a.id=op.artist_id JOIN customers c ON c.id=o.customer_id JOIN shops s ON s.id=op.shop_id WHERE o.id=?""", (offer_id,))
        if not offer: raise HTTPException(404, "Offer not found")
        if offer["status"] != "SENT": raise HTTPException(400, "This offer is no longer active.")
        expiration = core.parse_datetime(offer["expires_at"])
        if expiration and core.datetime.now(core.timezone.utc) >= expiration:
            conn.rollback(); conn.close(); core.expire_offer_and_continue(offer_id)
            raise HTTPException(400, "This offer has expired and the next customer has been contacted.")

        calendar_owner_id = google_integration.calendar_user_for_artist(offer["artist_id"])
        start_iso = google_integration.slot_iso(offer["date"], offer["start_time"], offer["shop_timezone"])
        end_iso = google_integration.slot_iso(offer["date"], offer["end_time"], offer["shop_timezone"])
        if calendar_owner_id:
            try:
                available = google_integration.calendar_is_available_for_user(calendar_owner_id, start_iso, end_iso)
            except Exception as exc:
                core.event("calendar.availability_error", "opening", offer["opening_id"], str(exc)); available = None
            if available is False:
                core.db_execute(conn, "UPDATE openings SET status='NO_RECOVERY' WHERE id=?", (offer["opening_id"],))
                core.db_execute(conn, "UPDATE offers SET status='CANCELLED', responded_at=? WHERE opening_id=? AND status IN ('PENDING','SENT')", (core.now_iso(), offer["opening_id"]))
                conn.commit(); conn.close()
                core.event("calendar.claim_blocked_busy", "opening", offer["opening_id"])
                raise HTTPException(409, "That time was just booked elsewhere. This offer is no longer available.")

        timestamp = core.now_iso()
        opening_cursor = core.db_execute(conn, "UPDATE openings SET status='CLAIMED' WHERE id=? AND status IN ('OPEN','RECOVERY_ACTIVE')", (offer["opening_id"],))
        if opening_cursor.rowcount != 1:
            conn.rollback(); raise HTTPException(409, "Someone else claimed this opening first.")
        offer_cursor = core.db_execute(conn, "UPDATE offers SET status='CLAIMED', claimed_at=?, responded_at=? WHERE id=? AND status='SENT'", (timestamp, timestamp, offer_id))
        if offer_cursor.rowcount != 1:
            conn.rollback(); raise HTTPException(409, "This offer is no longer active.")

        booking_id = f"booking_{uuid.uuid4().hex[:12]}"
        shop = core.db_fetchone(conn, "SELECT booking_url FROM shops WHERE id=?", (offer["shop_id"],))
        booking_url = shop["booking_url"] if shop else None
        core.db_execute(conn, "UPDATE offers SET status='CANCELLED' WHERE opening_id=? AND id!=? AND status IN ('PENDING','SENT')", (offer["opening_id"], offer_id))
        core.db_execute(conn, "INSERT INTO bookings(id,opening_id,customer_id,artist_id,booking_url,status,amount,booked_at) VALUES (?,?,?,?,?,?,?,?)", (booking_id, offer["opening_id"], offer["customer_id"], offer["artist_id"], booking_url, "AWAITING_CONFIRMATION", offer["price"], None))
        core.db_execute(conn, "UPDATE openings SET booking_id=? WHERE id=?", (booking_id, offer["opening_id"]))
        conn.commit()
    except HTTPException:
        try: conn.rollback(); conn.close()
        except Exception: pass
        raise
    except Exception:
        conn.rollback(); conn.close(); raise
    conn.close()

    core.event("offer.claimed", "offer", offer_id); core.event("booking.created", "booking", booking_id)
    try: core.send_recovery_email(offer["opening_id"])
    except Exception as exc: print("Recovery confirmation send failed:", str(exc))
    return RedirectResponse(f"/booking/{booking_id}", status_code=303)
