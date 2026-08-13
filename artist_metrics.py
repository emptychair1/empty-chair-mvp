"""Artist roster metrics and polished Artists page for Empty Chair.

Utilization is intentionally forward-looking for the Autopilot product model:
booked/claimed/completed slots divided by all non-cancelled slots created for
an artist from today through the next 30 days.
"""

from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import google_integration


app = core.app


def _remove_route(path, method):
    method = method.upper()
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


def _row_value(row, key, default=0):
    if not row:
        return default
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _artist_utilization(conn, artist_id, shop_id, start_date, end_date):
    row = core.db_fetchone(
        conn,
        """
        SELECT
            COUNT(*) AS total_slots,
            SUM(
                CASE
                    WHEN status IN ('CLAIMED', 'BOOKED', 'COMPLETED') THEN 1
                    ELSE 0
                END
            ) AS booked_slots
        FROM openings
        WHERE artist_id = ?
          AND shop_id = ?
          AND date >= ?
          AND date <= ?
          AND status <> 'CANCELLED'
        """,
        (artist_id, shop_id, start_date, end_date),
    )

    total_slots = int(_row_value(row, "total_slots", 0) or 0)
    booked_slots = int(_row_value(row, "booked_slots", 0) or 0)
    available_slots = max(total_slots - booked_slots, 0)
    utilization = round((booked_slots / total_slots * 100), 1) if total_slots else 0.0

    return {
        "utilization": utilization,
        "total_slots": total_slots,
        "booked_slots": booked_slots,
        "available_slots": available_slots,
    }


_remove_route("/artists", "GET")


@app.get("/artists", response_class=HTMLResponse)
def artists_page_v2(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    today = datetime.now(timezone.utc).date()
    end_date = today + timedelta(days=30)
    start_date_text = today.isoformat()
    end_date_text = end_date.isoformat()

    conn = core.connect()
    try:
        shop = core.db_fetchone(
            conn,
            "SELECT * FROM shops WHERE id = ? LIMIT 1",
            (user["shop_id"],),
        )
        artist_rows = core.db_fetchall(
            conn,
            """
            SELECT *
            FROM artists
            WHERE shop_id = ?
            ORDER BY active DESC, name
            """,
            (user["shop_id"],),
        )

        artists = []
        for row in artist_rows:
            artist = dict(row)
            artist.update(
                _artist_utilization(
                    conn,
                    artist["id"],
                    user["shop_id"],
                    start_date_text,
                    end_date_text,
                )
            )
            artist["calendar_connected"] = google_integration.artist_calendar_connected(artist["id"])
            artists.append(artist)
    finally:
        conn.close()

    active_artists = sum(1 for artist in artists if artist["active"])
    tracked_slots = sum(artist["total_slots"] for artist in artists)
    booked_slots = sum(artist["booked_slots"] for artist in artists)
    roster_utilization = (
        round((booked_slots / tracked_slots * 100), 1)
        if tracked_slots
        else 0.0
    )

    return core.templates.TemplateResponse(
        request=request,
        name="artists.html",
        context={
            "user": user,
            "shop": shop,
            "artists": artists,
            "active_artists": active_artists,
            "tracked_slots": tracked_slots,
            "roster_utilization": roster_utilization,
            "utilization_window": "Next 30 days",
        },
    )
