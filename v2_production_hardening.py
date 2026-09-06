"""Production hardening for Empty Chair 2.0.

Keeps the headless product quiet on the happy path while making background failures
observable and isolated. One broken artist/calendar/payment account must never stop
protection for the rest of the fleet.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import v2_app as core
import v2_artist_payments as payments


def _safe_event(kind: str, artist_id: str | None, payload: dict):
    try:
        core.event(kind, artist_id, payload)
    except Exception as exc:
        print(f"Empty Chair diagnostic event failed: {kind}: {type(exc).__name__}: {exc}", flush=True)


def _stamp(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _recent(kind: str, artist_id: str, minutes: int) -> bool:
    try:
        row = core.one(
            "SELECT created_at FROM events WHERE artist_id=? AND kind=? ORDER BY created_at DESC LIMIT 1",
            (artist_id, kind),
        )
        stamp = _stamp(row["created_at"]) if row else None
        return bool(stamp and datetime.now(timezone.utc) - stamp < timedelta(minutes=minutes))
    except Exception:
        return False


def _artist_alert(artist_id: str, kind: str, text: str, cooldown_minutes: int = 720):
    if _recent(kind, artist_id, cooldown_minutes):
        return
    artist = core.one("SELECT * FROM artists WHERE id=?", (artist_id,))
    if not artist:
        return
    accepted = bool(core.send_sms(artist.get("phone"), text))
    _safe_event(kind if accepted else f"{kind}.delivery_failed", artist_id, {"sms_accepted": accepted})


_original_poll_calendar = core.poll_calendar


def poll_calendar(artist_id: str):
    """Contain calendar failures to one artist and leave a durable diagnostic trail."""
    try:
        return _original_poll_calendar(artist_id)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"[:500]
        print(f"Empty Chair calendar isolation // artist={artist_id} // {detail}", flush=True)
        _safe_event("calendar.worker_failed", artist_id, {"error": detail})
        _artist_alert(
            artist_id,
            "alert.calendar.worker",
            "EMPTY CHAIR // CHECK CALENDAR\n\nWe hit a problem reading your\ntattoo calendar.\n\nYour chair isn't covered\nuntil we reconnect.\n\n" + core.BASE_URL + "/setup/calendar",
        )
        return None


def _payment_ready(artist_id: str) -> tuple[bool, str]:
    """Verify that a replacement client can actually pay before an offer leaves."""
    try:
        acct = payments.square_account(artist_id)
        if not acct:
            return False, "square_not_connected"
        if not acct.get("location_id"):
            return False, "square_location_missing"
        token = payments.square_token(acct)
        if not token:
            return False, "square_token_missing"
        return True, "ok"
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"[:300]
        print(f"Empty Chair payment readiness failed // artist={artist_id} // {detail}", flush=True)
        _safe_event("payment.readiness_error", artist_id, {"error": detail})
        return False, "square_refresh_failed"


_original_send_next_offer = core.send_next_offer


def send_next_offer(opening_id: str):
    """Do not invite a customer into a chair that cannot accept its deposit."""
    opening = core.one("SELECT * FROM openings WHERE id=?", (opening_id,))
    if not opening or opening.get("status") != "OPEN":
        return None

    ready, reason = _payment_ready(opening["artist_id"])
    if not ready:
        if not _recent("payment.recovery_blocked", opening["artist_id"], 5):
            _safe_event(
                "payment.recovery_blocked",
                opening["artist_id"],
                {"opening_id": opening_id, "reason": reason},
            )
        _artist_alert(
            opening["artist_id"],
            "alert.payment",
            "EMPTY CHAIR // CHECK PAYMENT\n\nWe found an open chair, but\nyour deposit connection needs\nattention before we can offer it.\n\nNo client has been contacted yet.\n\n" + core.BASE_URL + "/settings/payments",
            cooldown_minutes=120,
        )
        return None

    return _original_send_next_offer(opening_id)


def _resume_after_payment_reconnect(artist_id: str):
    """A successful Square reconnect should restart any chair paused for payment."""
    try:
        blocked = core.one(
            "SELECT created_at FROM events WHERE artist_id=? AND kind='payment.recovery_blocked' ORDER BY created_at DESC LIMIT 1",
            (artist_id,),
        )
        connected = core.one(
            "SELECT created_at FROM events WHERE artist_id=? AND kind='payment.square.connected' ORDER BY created_at DESC LIMIT 1",
            (artist_id,),
        )
        blocked_at = _stamp(blocked["created_at"]) if blocked else None
        connected_at = _stamp(connected["created_at"]) if connected else None
        if not blocked_at or not connected_at or connected_at <= blocked_at:
            return
        openings = core.all_rows(
            "SELECT id FROM openings WHERE artist_id=? AND status='OPEN' ORDER BY created_at",
            (artist_id,),
        )
        for opening in openings:
            active = core.one(
                "SELECT id FROM offers WHERE opening_id=? AND status IN ('SENT','HOLDING') LIMIT 1",
                (opening["id"],),
            )
            if not active:
                send_next_offer(opening["id"])
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"[:500]
        print(f"Empty Chair payment resume isolated // artist={artist_id} // {detail}", flush=True)
        _safe_event("payment.resume_failed", artist_id, {"error": detail})


def _safe_expire_offers():
    try:
        core.expire_offers()
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"[:500]
        print(f"Empty Chair offer expiry error // {detail}", flush=True)
        _safe_event("worker.offer_expiry_failed", None, {"error": detail})


def worker_tick():
    """Run every artist independently so one account can never abort the whole tick."""
    _safe_expire_offers()
    try:
        artists = core.all_rows("SELECT * FROM artists WHERE setup_state='ARMED'")
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"[:500]
        print(f"Empty Chair worker artist query failed // {detail}", flush=True)
        _safe_event("worker.artist_query_failed", None, {"error": detail})
        return

    for artist in artists:
        aid = artist["id"]
        try:
            poll_calendar(aid)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"[:500]
            print(f"Empty Chair worker artist failed // artist={aid} // {detail}", flush=True)
            _safe_event("worker.artist_failed", aid, {"stage": "calendar", "error": detail})
        try:
            _resume_after_payment_reconnect(aid)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"[:500]
            _safe_event("worker.artist_failed", aid, {"stage": "payment_resume", "error": detail})
        try:
            core.send_digests_if_due(artist)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"[:500]
            print(f"Empty Chair digest isolated // artist={aid} // {detail}", flush=True)
            _safe_event("worker.artist_failed", aid, {"stage": "digest", "error": detail})


core.poll_calendar = poll_calendar
core.worker_tick = worker_tick
core.send_next_offer = send_next_offer


_original_create_opening = core.create_opening_from_appointment


def create_opening_from_appointment(appt: dict):
    try:
        existing = core.one("SELECT id FROM openings WHERE source_appointment_id=? LIMIT 1", (appt["id"],))
        if existing:
            return None
        return _original_create_opening(appt)
    except Exception as exc:
        aid = appt.get("artist_id") if isinstance(appt, dict) else None
        detail = f"{type(exc).__name__}: {exc}"[:500]
        print(f"Empty Chair opening creation failed // artist={aid} // {detail}", flush=True)
        _safe_event(
            "opening.create_failed",
            aid,
            {"appointment_id": appt.get("id") if isinstance(appt, dict) else None, "error": detail},
        )
        return None


core.create_opening_from_appointment = create_opening_from_appointment

print("Empty Chair 2.0 production hardening loaded // calendar + payment + worker isolation", flush=True)
