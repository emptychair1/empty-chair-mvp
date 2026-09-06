"""Temporary production-safe simulator for the post-trial artist experience.

This exists only to let a logged-in artist simulate Day 8 without waiting seven days.
It affects only the currently signed-in artist and does not charge anything.
Remove after the post-trial flow is proven.
"""
from datetime import datetime, timedelta, timezone
from fastapi import Request
from fastapi.responses import RedirectResponse
import v2_app as core


@core.app.get("/__test/day8")
def simulate_day8(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/", status_code=303)

    ended = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    core.run(
        "UPDATE artists SET trial_ends_at=?,subscription_status='trialing',subscription_provider=NULL,subscription_customer_id=NULL,subscription_id=NULL,subscription_period_end=NULL,updated_at=? WHERE id=?",
        (ended, core.utcnow(), artist["id"]),
    )
    core.event("trial.test_day8", artist["id"], {"trial_ends_at": ended})
    return RedirectResponse("/paywall", status_code=303)


print("Empty Chair 2.0 Day-8 simulator loaded", flush=True)
