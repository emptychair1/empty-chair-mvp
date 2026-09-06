"""Native-device booking finalization boundary.

For EventKit / Android Calendar Provider, a server-side queue entry is not the same as a
calendar write. Mark the booking as pending, show calendar [!], and let the device ACK
turn it into calendar [✓]. Non-native providers keep the hardened server write path.
"""
from __future__ import annotations

import v2_app as core
import v2_native_calendar as native_calendar

_original_finalize = core.finalize_booking


def finalize_booking(offer:dict, provider:str, payment_id:str|None):
    opening=core.one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],))
    if not opening:return None
    acct=core.one("SELECT * FROM calendar_accounts WHERE artist_id=?",(opening["artist_id"],))
    if not acct or acct.get("provider")!="native":
        return _original_finalize(offer,provider,payment_id)

    existing=core.one("SELECT * FROM bookings WHERE opening_id=?",(opening["id"],))
    if existing:return existing
    client=core.one("SELECT * FROM clients WHERE id=?",(offer["client_id"],));artist=core.one("SELECT * FROM artists WHERE id=?",(opening["artist_id"],));booking_id=str(core.uuid.uuid4())
    try:
        core.run("INSERT INTO bookings(id,opening_id,client_id,provider,payment_id,amount_cents,remote_event_id,created_at) VALUES(?,?,?,?,?,?,NULL,?)",(booking_id,opening["id"],client["id"],provider,payment_id,opening["deposit_cents"],core.utcnow()))
    except Exception:
        existing=core.one("SELECT * FROM bookings WHERE opening_id=?",(opening["id"],))
        if existing:return existing
        raise
    core.run("UPDATE offers SET status='YOURS' WHERE id=?",(offer["id"],))
    core.run("UPDATE offers SET status='TAKEN' WHERE opening_id=? AND id<>? AND status IN ('PENDING','SENT','HOLDING','RETRY')",(opening["id"],offer["id"]))
    core.run("UPDATE openings SET status='FILLED' WHERE id=?",(opening["id"],))
    try:
        command_id=native_calendar.queue_event_write(artist["id"],f"{client['name']} // Tattoo",opening["starts_at"],opening["ends_at"],"Filled by Empty Chair",booking_id=booking_id,opening_id=opening["id"])
        core.run("UPDATE bookings SET remote_event_id=? WHERE id=?",(f"pending:{command_id}",booking_id))
        core.event("calendar.native_write_queued",artist["id"],{"opening_id":opening["id"],"booking_id":booking_id,"command_id":command_id})
    except Exception as exc:
        core.event("calendar.write_error",artist["id"],{"opening_id":opening["id"],"booking_id":booking_id,"error":f"{type(exc).__name__}: {exc}"[:500]})

    core.send_sms(artist.get("phone"),"EMPTY CHAIR // FILLED ✓\n\n"+client["name"]+" took "+core.fmt_when(opening["starts_at"])+".\n\ndeposit........"+core.fmt_money(opening["deposit_cents"])+" [✓]\ncalendar.................[!]\n\n"+core.fmt_money(opening["value_cents"])+" SAVED")
    text="EMPTY CHAIR // YOURS\n\n+----------------------+\n|     TAKE A SEAT.     |\n+----------------------+\n\n"+artist["name"]+"\n"+core.fmt_when(opening["starts_at"])+"\n\ndeposit.........."+core.fmt_money(opening["deposit_cents"])+" [✓]\nappointment...........[✓]\n\nYou're booked."
    core.send_sms(client.get("phone"),text)
    core.event("opening.filled",artist["id"],{"opening_id":opening["id"],"booking_id":booking_id,"client_id":client["id"],"payment_provider":provider,"calendar_ok":False,"calendar_native_pending":True})
    return core.one("SELECT * FROM bookings WHERE id=?",(booking_id,))


core.finalize_booking=finalize_booking
print("Empty Chair 2.0 native finalize bridge loaded // calendar ack required",flush=True)
