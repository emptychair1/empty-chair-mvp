"""Seven-day trial and subscription entitlement for Empty Chair 2.0."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import Request
from fastapi.responses import RedirectResponse
import v2_app as core

TRIAL_DAYS = 7


def _dt(value: str | None):
    if not value: return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception: return None


def ensure_schema():
    additions = (
        ("trial_started_at", "TEXT"),
        ("trial_ends_at", "TEXT"),
        ("subscription_status", "TEXT NOT NULL DEFAULT 'trialing'"),
        ("subscription_provider", "TEXT"),
        ("subscription_customer_id", "TEXT"),
        ("subscription_id", "TEXT"),
        ("subscription_period_end", "TEXT"),
    )
    for name, ddl in additions:
        try: core.run(f"ALTER TABLE artists ADD COLUMN {name} {ddl}")
        except Exception: pass
    try: artists = core.all_rows("SELECT * FROM artists")
    except Exception: return
    for artist in artists:
        if not artist.get("trial_started_at"):
            start = _dt(artist.get("created_at")) or datetime.now(timezone.utc)
            core.run("UPDATE artists SET trial_started_at=?,trial_ends_at=? WHERE id=?", (start.isoformat(), (start + timedelta(days=TRIAL_DAYS)).isoformat(), artist["id"]))


def state(artist: dict | None) -> str:
    if not artist: return "anonymous"
    status = (artist.get("subscription_status") or "trialing").lower()
    if status in ("active", "trialing_paid"): return "active"
    if status in ("past_due", "unpaid"): return "past_due"
    end = _dt(artist.get("trial_ends_at"))
    if end and datetime.now(timezone.utc) < end: return "trial"
    return "expired"


def allowed(artist: dict | None) -> bool:
    return state(artist) in ("trial", "active")


def activate(artist_id: str, provider: str, customer_id: str | None = None, subscription_id: str | None = None, period_end: str | None = None):
    core.run("UPDATE artists SET subscription_status='active',subscription_provider=?,subscription_customer_id=?,subscription_id=?,subscription_period_end=?,updated_at=? WHERE id=?", (provider, customer_id, subscription_id, period_end, core.utcnow(), artist_id))
    core.event("subscription.active", artist_id, {"provider": provider, "subscription_id": subscription_id})


def deactivate(artist_id: str, status: str = "canceled"):
    core.run("UPDATE artists SET subscription_status=?,updated_at=? WHERE id=?", (status, core.utcnow(), artist_id))
    core.event("subscription.inactive", artist_id, {"status": status})


def trial_copy(artist: dict) -> str:
    end = _dt(artist.get("trial_ends_at"))
    if not end: return "7-DAY FULL TRIAL"
    remaining = max(0, int((end - datetime.now(timezone.utc)).total_seconds() // 86400) + 1)
    return f"FULL TRIAL // {remaining} DAY{'S' if remaining != 1 else ''} LEFT"


# Do not start a new recovery without entitlement. An opening already underway is
# deliberately allowed to finish if the trial expires mid-recovery.
_original_create_opening = core.create_opening_from_appointment
def create_opening_entitled(appt: dict):
    artist = core.one("SELECT * FROM artists WHERE id=?", (appt["artist_id"],))
    if not allowed(artist):
        core.event("recovery.blocked.entitlement", appt["artist_id"], {"appointment_id": appt.get("id"), "state": state(artist)})
        return
    return _original_create_opening(appt)
core.create_opening_from_appointment = create_opening_entitled


@core.app.on_event("startup")
def entitlement_startup():
    # core.init_db runs first; this makes fresh installs and existing DBs both safe.
    ensure_schema()


@core.app.get("/paywall")
def paywall(request: Request):
    artist = core.current_artist(request)
    if not artist: return RedirectResponse("/setup")
    artist = core.one("SELECT * FROM artists WHERE id=?", (artist["id"],))
    if allowed(artist): return RedirectResponse("/", status_code=303)
    label = "PAYMENT REQUIRED" if state(artist) == "expired" else "CHECK PAYMENT"
    return core.page("Subscription Required", f'''<div class="center"><h1>EMPTY CHAIR // {label}</h1><p>Your 7-day full trial has ended.</p><p class="bright">Keep your chair covered.</p><div class="space"></div><a class="button" href="/settings/subscription">CHOOSE A PLAN</a><p class="dim">Your account and settings stay here. Recovery resumes when payment is confirmed.</p></div>''', chair=True)


# Existing production DB is already initialized at import time; best-effort migration now,
# then startup repeats it safely for fresh databases.
ensure_schema()
print("Empty Chair 2.0 entitlement loaded // 7-day full trial", flush=True)
