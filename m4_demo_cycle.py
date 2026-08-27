"""Synthetic-only M4 end-to-end demo helpers.

Adds a narrated observable recovery cycle for the isolated demo shop. No external
recipient is contacted. The claim endpoint mutates only demo records so the UI can
show offer -> claim -> booking -> calendar -> recovered revenue.
"""
import os
import uuid

from fastapi import Form, Request
from fastapi.responses import JSONResponse

import app as core

DEMO_SHOP_ID = "shop_live_demo"
DEMO_USER_ID = "user_live_demo"

NARRATION = {
    "scan": "I’m starting with the chair, not the customer list. Empty time is perishable inventory, so I’m looking for the highest-value gap first.",
    "filter": "Now I’m removing anyone I should not contact and narrowing the pool to customers with real evidence of fit.",
    "fit": "I’m comparing artist preference, tattoo style, price history, and the model’s estimate of incremental lift. I care less about who might book eventually and more about who is more likely to book because I act now.",
    "choose": "I have a leader. I’m sending the first offer to the customer with the strongest combined fit, uplift, and confidence. One customer first. No spray and pray.",
    "sent": "Offer sent. Now I wait for behavior. A response is data, and data changes the next move.",
    "claimed": "Claim received. I’m closing the recovery loop, creating the booking, and moving that recovered revenue back onto the calendar.",
    "learn": "The chair is filled. I keep the outcome as evidence, because every accepted, declined, and expired offer should make the next decision less stupid. Progress is mostly organized embarrassment.",
}


def _demo_user(request):
    user = core.get_current_user(request)
    return user if user and user["id"] == DEMO_USER_ID and user["shop_id"] == DEMO_SHOP_ID else None


@core.app.post("/api/m4/operator/narrate")
def narrate_m4(request: Request, key: str = Form(...)):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    text = NARRATION.get((key or "").strip())
    if not text:
        return JSONResponse({"error": "Unknown narration step."}, status_code=400)
    try:
        import meeting_v2
        meeting_v2.ELEVENLABS_VOICE_ID = os.getenv("M4_ELEVENLABS_VOICE_ID", meeting_v2.ELEVENLABS_VOICE_ID)
        meeting_v2.ELEVENLABS_MODEL_ID = os.getenv("M4_ELEVENLABS_MODEL_ID", meeting_v2.ELEVENLABS_MODEL_ID)
        audio64 = meeting_v2._speak(text)
        return JSONResponse({"ok": True, "text": text, "audio_base64": audio64}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"ok": True, "text": text, "audio_base64": None, "voice_error": str(exc)}, headers={"Cache-Control": "no-store"})


@core.app.post("/api/m4/operator/demo-claim")
def demo_claim(request: Request, opening_id: str = Form(...), offer_id: str = Form(...)):
    if not _demo_user(request):
        return JSONResponse({"error": "Synthetic claim is demo-only."}, status_code=403)
    conn = core.connect()
    try:
        opening = core.db_fetchone(conn, "SELECT * FROM openings WHERE id=? AND shop_id=? LIMIT 1", (opening_id, DEMO_SHOP_ID))
        offer = core.db_fetchone(conn, "SELECT * FROM offers WHERE id=? AND opening_id=? LIMIT 1", (offer_id, opening_id))
        if not opening or not offer:
            return JSONResponse({"error": "Opening or synthetic offer not found."}, status_code=404)
        customer = core.db_fetchone(conn, "SELECT * FROM customers WHERE id=? AND shop_id=? LIMIT 1", (offer["customer_id"], DEMO_SHOP_ID))
        if not customer:
            return JSONResponse({"error": "Synthetic customer not found."}, status_code=404)
        booking_id = f"demo_m4_booking_{uuid.uuid4().hex[:10]}"
        now = core.now_iso()
        core.db_execute(conn, "UPDATE offers SET status='CLAIMED',claimed_at=?,responded_at=? WHERE id=?", (now, now, offer_id))
        core.db_execute(conn, "INSERT INTO bookings(id,opening_id,customer_id,artist_id,status,amount,deposit_amount,deposit_status,booked_at) VALUES (?,?,?,?,?,?,?,?,?)", (booking_id, opening_id, customer["id"], opening["artist_id"], "COMPLETED", float(opening["price"] or 0), 0, "NOT_REQUIRED", now))
        core.db_execute(conn, "UPDATE openings SET status='COMPLETED',booking_id=? WHERE id=? AND shop_id=?", (booking_id, opening_id, DEMO_SHOP_ID))
        conn.commit()
        amount = float(opening["price"] or 0)
        core.event("m4.synthetic_claimed", "booking", booking_id, f'{{"opening_id":"{opening_id}","offer_id":"{offer_id}","amount":{amount}}}')
        return JSONResponse({
            "ok": True,
            "booking_id": booking_id,
            "customer_id": customer["id"],
            "customer_name": customer["name"],
            "artist_id": opening["artist_id"],
            "date": opening["date"],
            "start_time": opening["start_time"],
            "end_time": opening["end_time"],
            "style": opening["style"],
            "amount": amount,
            "status": "COMPLETED",
        }, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        conn.rollback()
        return JSONResponse({"error": str(exc)}, status_code=409)
    finally:
        conn.close()
