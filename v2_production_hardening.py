"""Production hardening for Empty Chair 2.0.

Keeps the headless product quiet on the happy path while making background failures
observable and isolated. One broken artist/calendar must never stop protection for the
rest of the fleet.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import traceback

import v2_app as core


def _safe_event(kind: str, artist_id: str | None, payload: dict):
    try:
        core.event(kind, artist_id, payload)
    except Exception as exc:
        print(f"Empty Chair diagnostic event failed: {kind}: {type(exc).__name__}: {exc}", flush=True)


def _recent(kind: str, artist_id: str, minutes: int) -> bool:
    try:
        row = core.one(
            "SELECT created_at FROM events WHERE artist_id=? AND kind=? ORDER BY created_at DESC LIMIT 1",
            (artist_id, kind),
        )
        if not row:
            return False
        stamp = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - stamp < timedelta(minutes=minutes)
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
        except Exception as exc:  # belt-and-suspenders isolation
            detail = f"{type(exc).__name__}: {exc}"[:500]
            print(f"Empty Chair worker artist failed // artist={aid} // {detail}", flush=True)
            _safe_event("worker.artist_failed", aid, {"stage": "calendar", "error": detail})
        try:
            core.send_digests_if_due(artist)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"[:500]
            print(f"Empty Chair digest isolated // artist={aid} // {detail}", flush=True)
            _safe_event("worker.artist_failed", aid, {"stage": "digest", "error": detail})


# Patch globals used dynamically by the already-running worker loop. The loop resolves
# core.worker_tick on every cycle, so this takes effect without replacing the worker.
core.poll_calendar = poll_calendar
core.worker_tick = worker_tick


# Guard the opening creator too. Calendar providers can report the same deletion more
# than once; source_appointment_id is the idempotency key and the core creator already
# checks it. Record unexpected failures without allowing them to poison the worker tick.
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
        _safe_event("opening.create_failed", aid, {"appointment_id": appt.get("id") if isinstance(appt, dict) else None, "error": detail})
        return None


core.create_opening_from_appointment = create_opening_from_appointment

print("Empty Chair 2.0 production hardening loaded", flush=True)
