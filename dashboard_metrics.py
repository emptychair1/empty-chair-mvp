"""Utilization-first dashboard for Empty Chair.

This replaces the legacy dashboard route without changing recovery, claim,
notification, booking, or Autopilot behavior.
"""

from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core
import artist_metrics
import onboarding


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


_remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def dashboard_v2(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    if onboarding.needs_onboarding(user["shop_id"]):
        return RedirectResponse("/setup", status_code=303)

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
                artist_metrics._artist_utilization(
                    conn,
                    artist["id"],
                    user["shop_id"],
                    start_date_text,
                    end_date_text,
                )
            )
            artists.append(artist)

        recent_openings = core.db_fetchall(
            conn,
            """
            SELECT o.*, a.name AS artist_name
            FROM openings o
            JOIN artists a ON a.id = o.artist_id
            WHERE o.shop_id = ?
            ORDER BY o.created_at DESC
            LIMIT 8
            """,
            (user["shop_id"],),
        )

        live_recovery = core.db_fetchone(
            conn,
            """
            SELECT o.*, a.name AS artist_name
            FROM openings o
            JOIN artists a ON a.id = o.artist_id
            WHERE o.shop_id = ?
              AND o.status = 'RECOVERY_ACTIVE'
            ORDER BY o.created_at DESC
            LIMIT 1
            """,
            (user["shop_id"],),
        )

        customer_row = core.db_fetchone(
            conn,
            "SELECT COUNT(*) AS n FROM customers WHERE shop_id = ?",
            (user["shop_id"],),
        )

        revenue_row = core.db_fetchone(
            conn,
            """
            SELECT COALESCE(SUM(price), 0) AS total
            FROM openings
            WHERE shop_id = ?
              AND status IN ('BOOKED', 'COMPLETED')
            """,
            (user["shop_id"],),
        )

        active_campaign_row = core.db_fetchone(
            conn,
            """
            SELECT COUNT(*) AS n
            FROM openings
            WHERE shop_id = ?
              AND status = 'RECOVERY_ACTIVE'
            """,
            (user["shop_id"],),
        )
    finally:
        conn.close()

    total_slots = sum(int(artist["total_slots"] or 0) for artist in artists)
    booked_slots = sum(int(artist["booked_slots"] or 0) for artist in artists)
    open_slots = max(total_slots - booked_slots, 0)
    shop_utilization = round((booked_slots / total_slots * 100), 1) if total_slots else 0.0

    active_artists = [artist for artist in artists if artist["active"]]
    needs_fill = sorted(
        [artist for artist in active_artists if artist["total_slots"] > 0],
        key=lambda artist: (artist["utilization"], -artist["available_slots"]),
    )

    recovered_revenue = float(_row_value(revenue_row, "total", 0) or 0)
    customer_count = int(_row_value(customer_row, "n", 0) or 0)
    active_campaigns = int(_row_value(active_campaign_row, "n", 0) or 0)

    return core.templates.TemplateResponse(
        request=request,
        name="dashboard_v2.html",
        context={
            "user": user,
            "shop": shop,
            "artists": artists,
            "needs_fill": needs_fill,
            "shop_utilization": shop_utilization,
            "total_slots": total_slots,
            "booked_slots": booked_slots,
            "open_slots": open_slots,
            "recovered_revenue": recovered_revenue,
            "customer_count": customer_count,
            "active_campaigns": active_campaigns,
            "recent_openings": recent_openings,
            "live_recovery": live_recovery,
            "utilization_window": "Next 30 days",
        },
    )
