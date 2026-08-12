"""Canonical Fill Chairs GET/POST flow.

The page renders from database state only. Starting a campaign creates the
campaign/openings synchronously, redirects immediately, and activates offers in
a FastAPI background task so Google Calendar and notification work never blocks
the owner's browser request.
"""

import json
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core
import pilot

app = core.app


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


def _database_snapshot(shop_id: str) -> dict:
    """Return the Fill Chairs page snapshot without running Autopilot."""
    conn = core.connect()
    try:
        shop = core.db_fetchone(
            conn,
            "SELECT * FROM shops WHERE id = ? LIMIT 1",
            (shop_id,),
        )
        artists = pilot._count(
            conn,
            "SELECT COUNT(*) AS total FROM artists WHERE shop_id = ? AND active = 1",
            (shop_id,),
        )
        customers = pilot._count(
            conn,
            "SELECT COUNT(*) AS total FROM customers WHERE shop_id = ?",
            (shop_id,),
        )
        consented_customers = pilot._count(
            conn,
            "SELECT COUNT(*) AS total FROM customers WHERE shop_id = ? AND communication_consent = 1",
            (shop_id,),
        )
        openings = pilot._count(
            conn,
            "SELECT COUNT(*) AS total FROM openings WHERE shop_id = ?",
            (shop_id,),
        )
        recovered = pilot._count(
            conn,
            "SELECT COUNT(*) AS total FROM openings WHERE shop_id = ? AND status IN ('BOOKED','COMPLETED')",
            (shop_id,),
        )
        offers = pilot._count(
            conn,
            """
            SELECT COUNT(*) AS total
            FROM offers ofr
            JOIN openings o ON o.id = ofr.opening_id
            WHERE o.shop_id = ?
            """,
            (shop_id,),
        )
        claimed_offers = pilot._count(
            conn,
            """
            SELECT COUNT(*) AS total
            FROM offers ofr
            JOIN openings o ON o.id = ofr.opening_id
            WHERE o.shop_id = ? AND ofr.status = 'CLAIMED'
            """,
            (shop_id,),
        )
        revenue_row = core.db_fetchone(
            conn,
            """
            SELECT COALESCE(SUM(price), 0) AS total
            FROM openings
            WHERE shop_id = ? AND status IN ('BOOKED','COMPLETED')
            """,
            (shop_id,),
        )
    finally:
        conn.close()

    campaigns = pilot._campaign_rows(shop_id)
    checks = [
        {
            "key": "shop",
            "label": "Studio configured",
            "ok": bool(shop and shop["name"]),
            "detail": shop["name"] if shop else "No studio record",
            "required": True,
        },
        {
            "key": "artists",
            "label": "At least one active artist",
            "ok": artists > 0,
            "detail": f"{artists} active artist{'s' if artists != 1 else ''}",
            "required": True,
        },
        {
            "key": "customers",
            "label": "Consented customer audience",
            "ok": consented_customers > 0,
            "detail": f"{consented_customers} consented of {customers} total",
            "required": True,
        },
    ]
    passed = sum(1 for item in checks if item["ok"])

    return {
        "version": pilot.PILOT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready": all(item["ok"] for item in checks),
        "readiness_percent": round(passed / len(checks) * 100) if checks else 0,
        "checks": checks,
        "metrics": {
            "artists": artists,
            "customers": customers,
            "consented_customers": consented_customers,
            "openings": openings,
            "recovered_openings": recovered,
            "recovery_rate": round(recovered / openings * 100, 1) if openings else 0.0,
            "offers": offers,
            "claimed_offers": claimed_offers,
            "offer_conversion_rate": round(claimed_offers / offers * 100, 1) if offers else 0.0,
            "recovered_revenue": pilot._money(revenue_row["total"] if revenue_row else 0),
            "active_autopilot_campaigns": sum(
                1 for item in campaigns if item["status"] == "ACTIVE"
            ),
        },
        "campaigns": campaigns,
    }


def _activate_shop(shop_id: str) -> None:
    """Activate up to the configured window without blocking the POST request."""
    try:
        campaigns = pilot._campaign_rows(shop_id)
        for campaign in campaigns:
            if campaign["status"] != "ACTIVE":
                continue

            if campaign["utilization"] >= campaign["target_utilization"]:
                conn = core.connect()
                try:
                    core.db_execute(
                        conn,
                        """
                        UPDATE autopilot_campaigns
                        SET status = 'TARGET_REACHED', stopped_at = ?
                        WHERE id = ? AND status = 'ACTIVE'
                        """,
                        (core.now_iso(), campaign["id"]),
                    )
                    conn.commit()
                finally:
                    conn.close()
                continue

            capacity = max(
                0,
                pilot.AUTOPILOT_ACTIVE_WINDOW - campaign["active_slots"],
            )
            if capacity <= 0:
                continue

            conn = core.connect()
            try:
                candidates = core.db_fetchall(
                    conn,
                    """
                    SELECT o.id
                    FROM autopilot_campaign_openings co
                    JOIN openings o ON o.id = co.opening_id
                    WHERE co.campaign_id = ?
                      AND o.status = 'OPEN'
                    ORDER BY o.date, o.start_time
                    LIMIT ?
                    """,
                    (campaign["id"], capacity),
                )
            finally:
                conn.close()

            for candidate in candidates:
                try:
                    # core.start_recovery_campaign is already wrapped by
                    # calendar_safety, so this is the single pre-offer
                    # Google Calendar check.
                    offer_id = core.start_recovery_campaign(candidate["id"])
                    if offer_id:
                        core.event(
                            "autopilot.slot_activated",
                            "opening",
                            candidate["id"],
                            json.dumps({"campaign_id": campaign["id"]}),
                        )
                except Exception as exc:
                    core.event(
                        "autopilot.activation_failed",
                        "opening",
                        candidate["id"],
                        json.dumps(
                            {
                                "campaign_id": campaign["id"],
                                "error": str(exc),
                            }
                        ),
                    )
    except Exception as exc:
        core.event("autopilot.background_failed", "shop", shop_id, str(exc))


_remove_route("/pilot", "GET")
_remove_route("/pilot/autopilot", "POST")


@app.get("/pilot", response_class=HTMLResponse)
def fill_chairs_page(request: Request, started: int = 0, error: str = ""):
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
            "pilot": _database_snapshot(user["shop_id"]),
            "started": started,
            "error": error,
            "today": today.isoformat(),
            "week_end": week_end.isoformat(),
            "month_end": month_end.isoformat(),
        },
    )


@app.post("/pilot/autopilot")
def start_filling(
    request: Request,
    background_tasks: BackgroundTasks,
    artist_id: str = Form(...),
    mode: str = Form("custom"),
    start_date: str = Form(...),
    end_date: str = Form(...),
    start_time: str = Form("12:00"),
    end_time: str = Form("20:00"),
    slot_minutes: int = Form(120),
    min_price: float = Form(250),
    target_utilization: int = Form(85),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    try:
        start = pilot._parse_date(start_date)
        end = pilot._parse_date(end_date)
        start_minutes = pilot._time_to_minutes(start_time)
        end_minutes = pilot._time_to_minutes(end_time)
    except (TypeError, ValueError):
        return RedirectResponse(
            "/pilot?error=Check+the+dates+and+times+and+try+again",
            status_code=303,
        )

    if end < start:
        return RedirectResponse(
            "/pilot?error=End+date+must+be+after+start+date",
            status_code=303,
        )
    if (end - start).days > 31:
        return RedirectResponse(
            "/pilot?error=Fill+Chairs+is+limited+to+31+days+at+a+time",
            status_code=303,
        )
    if end_minutes <= start_minutes:
        return RedirectResponse(
            "/pilot?error=End+time+must+be+after+start+time",
            status_code=303,
        )

    mode = (mode or "custom").strip().lower()
    if mode not in {"week", "month", "custom"}:
        mode = "custom"

    slot_minutes = min(max(int(slot_minutes), 30), 480)
    target_utilization = min(max(int(target_utilization), 10), 100)
    min_price = max(float(min_price), 0)

    conn = core.connect()
    try:
        artist = core.db_fetchone(
            conn,
            """
            SELECT id
            FROM artists
            WHERE id = ? AND shop_id = ? AND active = 1
            LIMIT 1
            """,
            (artist_id, user["shop_id"]),
        )
        if not artist:
            return RedirectResponse(
                "/pilot?error=Choose+a+valid+active+artist",
                status_code=303,
            )

        campaign_id = f"auto_{uuid.uuid4().hex[:12]}"
        core.db_execute(
            conn,
            """
            INSERT INTO autopilot_campaigns(
                id, shop_id, artist_id, mode, start_date, end_date,
                start_time, end_time, slot_minutes, min_price,
                target_utilization, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (
                campaign_id,
                user["shop_id"],
                artist_id,
                mode,
                start_date,
                end_date,
                start_time,
                end_time,
                slot_minutes,
                min_price,
                target_utilization,
                core.now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        created = pilot._create_campaign_openings(campaign_id)
    except Exception as exc:
        conn = core.connect()
        try:
            core.db_execute(
                conn,
                "UPDATE autopilot_campaigns SET status = 'STOPPED', stopped_at = ? WHERE id = ?",
                (core.now_iso(), campaign_id),
            )
            conn.commit()
        finally:
            conn.close()
        core.event("autopilot.creation_failed", "autopilot_campaign", campaign_id, str(exc))
        return RedirectResponse(
            "/pilot?error=Could+not+create+those+appointment+slots",
            status_code=303,
        )

    core.event(
        "autopilot.started",
        "autopilot_campaign",
        campaign_id,
        json.dumps({"slots_created": created, "mode": mode}),
    )

    # Calendar checks, customer ranking, and delivery happen after the redirect.
    background_tasks.add_task(_activate_shop, user["shop_id"])

    return RedirectResponse(f"/pilot?started={created}", status_code=303)
