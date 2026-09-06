"""Final production-safety pass for Empty Chair 2.0.

Hardens the money -> booking -> calendar boundary, restart recovery, worker heartbeat,
and removes test-payment completion from production routing.
"""
from __future__ import annotations

import hashlib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi.responses import JSONResponse

import v2_app as core


def _safe_event(kind: str, artist_id: str | None, payload: dict):
    try:
        core.event(kind, artist_id, payload)
    except Exception as exc:
        print(f"Empty Chair final hardening event failed // {kind} // {type(exc).__name__}: {exc}", flush=True)


def _event_id(booking_id: str) -> str:
    # Lower-case hex works as a Google event id and as an Apple iCalendar UID.
    return hashlib.sha256(booking_id.encode()).hexdigest()[:32]


def _write_calendar(booking: dict, opening: dict, artist: dict, client: dict) -> str:
    acct = core.one("SELECT * FROM calendar_accounts WHERE artist_id=?", (artist["id"],))
    if not acct:
        raise RuntimeError("calendar account missing")
    remote_id = _event_id(booking["id"])

    if acct["provider"] == "google":
        payload = {
            "id": remote_id,
            "summary": f"{client['name']} // Tattoo",
            "description": "Filled by Empty Chair",
            "start": {"dateTime": opening["starts_at"]},
            "end": {"dateTime": opening["ends_at"]},
        }
        if client.get("email"):
            payload["attendees"] = [{"email": client["email"]}]
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            + urllib.parse.quote(acct["calendar_id"] or "primary", safe="")
            + "/events"
        )
        try:
            core.http_json(
                url,
                "POST",
                payload,
                {"Authorization": f"Bearer {core.google_access_token(acct)}"},
            )
        except urllib.error.HTTPError as exc:
            # Deterministic id already exists: the prior write landed before a crash.
            if int(getattr(exc, "code", 0)) != 409:
                raise
        return remote_id

    dt = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Empty Chair//2.0//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{remote_id}\r\n"
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTSTART:{dt(opening['starts_at'])}\r\n"
        f"DTEND:{dt(opening['ends_at'])}\r\n"
        f"SUMMARY:{client['name']} // Tattoo\r\n"
        "DESCRIPTION:Filled by Empty Chair\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    ).encode()
    url = acct["apple_calendar_url"].rstrip("/") + "/" + remote_id + ".ics"
    auth = core.base64.b64encode(f"{acct['apple_username']}:{acct['apple_password']}".encode()).decode()
    req = urllib.request.Request(
        url,
        data=ics,
        method="PUT",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "text/calendar; charset=utf-8",
            "If-None-Match": "*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except urllib.error.HTTPError as exc:
        # 412 means this deterministic resource already exists, which is retry success.
        if int(getattr(exc, "code", 0)) != 412:
            raise
    return remote_id


def _alert_calendar_write(artist: dict, opening: dict):
    kind = "alert.calendar.write"
    try:
        recent = core.one(
            "SELECT id FROM events WHERE artist_id=? AND kind=? AND created_at>=? LIMIT 1",
            (artist["id"], kind, (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()),
        )
        if recent:
            return
    except Exception:
        pass
    accepted = bool(
        core.send_sms(
            artist.get("phone"),
            "EMPTY CHAIR // CHECK CALENDAR\n\n"
            "The deposit landed and the chair\n"
            "is filled, but we couldn't put the\n"
            "appointment back on your calendar.\n\n"
            "We're retrying automatically.\n\n"
            f"{core.BASE_URL}/setup/calendar",
        )
    )
    _safe_event(kind if accepted else f"{kind}.delivery_failed", artist["id"], {"opening_id": opening["id"]})


def _filled_sms(artist: dict, opening: dict, client: dict, calendar_ok: bool):
    calendar_line = "calendar.................[✓]" if calendar_ok else "calendar.................[!]"
    core.send_sms(
        artist.get("phone"),
        "EMPTY CHAIR // FILLED ✓\n\n"
        f"{client['name']} took {core.fmt_when(opening['starts_at'])}.\n\n"
        f"deposit........{core.fmt_money(opening['deposit_cents'])} [✓]\n"
        f"{calendar_line}\n\n"
        f"{core.fmt_money(opening['value_cents'])} SAVED",
    )


def _client_yours(artist: dict, opening: dict, client: dict):
    text = (
        "EMPTY CHAIR // YOURS\n\n"
        "+----------------------+\n"
        "|     TAKE A SEAT.     |\n"
        "+----------------------+\n\n"
        f"{artist['name']}\n"
        f"{core.fmt_when(opening['starts_at'])}\n\n"
        f"deposit..........{core.fmt_money(opening['deposit_cents'])} [✓]\n"
        "appointment...........[✓]\n\n"
        "You're booked."
    )
    core.send_sms(client.get("phone"), text)


def finalize_booking(offer: dict, provider: str, payment_id: str | None):
    """Finalize once even if payment callbacks/retries arrive more than once."""
    opening = core.one("SELECT * FROM openings WHERE id=?", (offer["opening_id"],))
    if not opening:
        return None
    existing = core.one("SELECT * FROM bookings WHERE opening_id=?", (opening["id"],))
    if existing:
        return existing

    client = core.one("SELECT * FROM clients WHERE id=?", (offer["client_id"],))
    artist = core.one("SELECT * FROM artists WHERE id=?", (opening["artist_id"],))
    booking_id = str(core.uuid.uuid4())

    # Reserve exactly one booking first. UNIQUE(opening_id) is the cross-process
    # idempotency boundary, before calendar writes or confirmation SMS can duplicate.
    try:
        core.run(
            "INSERT INTO bookings(id,opening_id,client_id,provider,payment_id,amount_cents,remote_event_id,created_at) "
            "VALUES(?,?,?,?,?,?,NULL,?)",
            (booking_id, opening["id"], client["id"], provider, payment_id, opening["deposit_cents"], core.utcnow()),
        )
    except Exception as exc:
        existing = core.one("SELECT * FROM bookings WHERE opening_id=?", (opening["id"],))
        if existing:
            _safe_event("booking.duplicate_finalize_ignored", artist["id"], {"opening_id": opening["id"]})
            return existing
        raise exc

    core.run("UPDATE offers SET status='YOURS' WHERE id=?", (offer["id"],))
    core.run(
        "UPDATE offers SET status='TAKEN' WHERE opening_id=? AND id<>? "
        "AND status IN ('PENDING','SENT','HOLDING','RETRY')",
        (opening["id"], offer["id"]),
    )
    core.run("UPDATE openings SET status='FILLED' WHERE id=?", (opening["id"],))

    booking = core.one("SELECT * FROM bookings WHERE id=?", (booking_id,))
    calendar_ok = False
    try:
        remote = _write_calendar(booking, opening, artist, client)
        core.run("UPDATE bookings SET remote_event_id=? WHERE id=?", (remote, booking_id))
        calendar_ok = True
        _safe_event("calendar.write_ok", artist["id"], {"opening_id": opening["id"], "booking_id": booking_id})
    except Exception as exc:
        _safe_event(
            "calendar.write_error",
            artist["id"],
            {"opening_id": opening["id"], "booking_id": booking_id, "error": f"{type(exc).__name__}: {exc}"[:500]},
        )
        _alert_calendar_write(artist, opening)

    _filled_sms(artist, opening, client, calendar_ok)
    _client_yours(artist, opening, client)
    _safe_event(
        "opening.filled",
        artist["id"],
        {
            "opening_id": opening["id"],
            "booking_id": booking_id,
            "client_id": client["id"],
            "payment_provider": provider,
            "calendar_ok": calendar_ok,
        },
    )
    return core.one("SELECT * FROM bookings WHERE id=?", (booking_id,))


def _retry_calendar_writebacks():
    rows = core.all_rows(
        "SELECT b.* FROM bookings b JOIN openings o ON o.id=b.opening_id "
        "WHERE b.remote_event_id IS NULL AND o.status='FILLED' ORDER BY b.created_at LIMIT 50"
    )
    for booking in rows:
        opening = core.one("SELECT * FROM openings WHERE id=?", (booking["opening_id"],))
        artist = core.one("SELECT * FROM artists WHERE id=?", (opening["artist_id"],))
        client = core.one("SELECT * FROM clients WHERE id=?", (booking["client_id"],))
        try:
            remote = _write_calendar(booking, opening, artist, client)
            core.run("UPDATE bookings SET remote_event_id=? WHERE id=?", (remote, booking["id"]))
            _safe_event("calendar.write_recovered", artist["id"], {"opening_id": opening["id"], "booking_id": booking["id"]})
            core.send_sms(
                artist.get("phone"),
                "EMPTY CHAIR // CALENDAR FIXED ✓\n\n"
                f"{core.fmt_when(opening['starts_at'])} is back on your calendar.\n\n"
                "Nothing else needed.",
            )
        except Exception as exc:
            _safe_event(
                "calendar.write_retry_failed",
                artist["id"],
                {"opening_id": opening["id"], "booking_id": booking["id"], "error": f"{type(exc).__name__}: {exc}"[:500]},
            )


def _recover_stale_holds():
    stale = core.all_rows(
        "SELECT * FROM offers WHERE status='HOLDING' AND expires_at IS NOT NULL AND expires_at<?",
        (core.utcnow(),),
    )
    for offer in stale:
        booking = core.one("SELECT id FROM bookings WHERE opening_id=? LIMIT 1", (offer["opening_id"],))
        if booking:
            core.run("UPDATE offers SET status='YOURS' WHERE id=?", (offer["id"],))
            continue
        opening = core.one("SELECT * FROM openings WHERE id=?", (offer["opening_id"],))
        core.run("UPDATE offers SET status='EXPIRED' WHERE id=?", (offer["id"],))
        _safe_event(
            "offer.hold_recovered",
            opening["artist_id"] if opening else None,
            {"offer_id": offer["id"], "opening_id": offer["opening_id"]},
        )
        core.send_next_offer(offer["opening_id"])


_last_worker_ok: str | None = None
_original_worker_tick = core.worker_tick


def worker_tick():
    global _last_worker_ok
    try:
        _recover_stale_holds()
    except Exception as exc:
        _safe_event("worker.hold_recovery_failed", None, {"error": f"{type(exc).__name__}: {exc}"[:500]})
    try:
        _retry_calendar_writebacks()
    except Exception as exc:
        _safe_event("worker.calendar_retry_failed", None, {"error": f"{type(exc).__name__}: {exc}"[:500]})
    _original_worker_tick()
    _last_worker_ok = core.utcnow()


core.finalize_booking = finalize_booking
core.worker_tick = worker_tick

# No-charge completion must not exist in a production router, even if a forgotten
# environment flag is accidentally enabled.
core.app.router.routes[:] = [
    r for r in core.app.router.routes if getattr(r, "path", None) != "/o/{token}/test-complete"
]

# Replace the shallow health endpoint with a worker-aware one.
core.app.router.routes[:] = [
    r for r in core.app.router.routes
    if not (getattr(r, "path", None) == "/healthz" and "GET" in (getattr(r, "methods", set()) or set()))
]


@core.app.get("/healthz")
def hardened_health():
    thread = getattr(core, "_worker_thread", None)
    alive = bool(thread and thread.is_alive()) if core.WORKER_ENABLED else True
    return JSONResponse(
        {
            "ok": alive,
            "product": "empty-chair",
            "version": core.VERSION,
            "worker_enabled": core.WORKER_ENABLED,
            "worker_alive": alive,
            "worker_last_ok": _last_worker_ok,
        },
        status_code=200 if alive else 503,
    )


print("Empty Chair 2.0 final production hardening loaded", flush=True)
