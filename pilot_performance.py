"""Performance patch for the Fill Chairs page.

The UI should render from local database state only. Google Calendar checks belong
in the activation/claim paths, not in a GET request that displays the page.
"""

from datetime import date, timedelta

from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import pilot

app = core.app


# pilot._autopilot_tick previously checked Google directly and then called
# core.start_recovery_campaign(), which is already protected by calendar_safety.
# Avoid that duplicate network round trip. The global safety wrapper remains the
# authoritative pre-offer check.
def _calendar_check_deferred_to_recovery_wrapper(owner, opening):
    return None


pilot._opening_calendar_available = _calendar_check_deferred_to_recovery_wrapper


def _remove_route(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


def _fast_snapshot(shop_id):
    """Read the current Pilot snapshot without activating openings during render."""
    original_tick = pilot._autopilot_tick
    try:
        pilot._autopilot_tick = lambda _shop_id: 0
        return pilot._shop_snapshot(shop_id)
    finally:
        pilot._autopilot_tick = original_tick


_remove_route("/pilot", "GET")


@app.get("/pilot", response_class=HTMLResponse)
def pilot_page_fast(request: Request, started: int = 0, error: str = ""):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        shop = core.db_fetchone(
            conn,
            "SELECT * FROM shops WHERE id = ? LIMIT 1",
            (user["shop_id"],),
        )
        artists = core.db_fetchall(
            conn,
            "SELECT * FROM artists WHERE shop_id = ? AND active = 1 ORDER BY name",
            (user["shop_id"],),
        )
    finally:
        conn.close()

    snapshot = _fast_snapshot(user["shop_id"])
    today = date.today()
    week_end = today + timedelta(days=6)
    month_end = min(
        today + timedelta(days=30),
        date(
            today.year + (today.month == 12),
            1 if today.month == 12 else today.month + 1,
            1,
        ) - timedelta(days=1),
    )

    return core.templates.TemplateResponse(
        request=request,
        name="pilot.html",
        context={
            "user": user,
            "shop": shop,
            "artists": artists,
            "pilot": snapshot,
            "started": started,
            "error": error,
            "today": today.isoformat(),
            "week_end": week_end.isoformat(),
            "month_end": month_end.isoformat(),
        },
    )
