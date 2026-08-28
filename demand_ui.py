"""App-native UI for the Demand Engine dashboard."""
from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import demand_acquisition


def _remove_route(path, method):
    method = method.upper()
    core.app.router.routes = [
        route
        for route in core.app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


_remove_route("/demand-acquisition", "GET")


@core.app.get("/demand-acquisition", response_class=HTMLResponse)
def demand_engine_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        demand_acquisition._ensure_tables(conn)
        shop = core.db_fetchone(
            conn,
            "SELECT * FROM shops WHERE id=? LIMIT 1",
            (user["shop_id"],),
        )
        identities = core.db_fetchall(
            conn,
            "SELECT * FROM acquisition_identities WHERE owner_shop_id=? AND status='active' ORDER BY created_at DESC",
            (user["shop_id"],),
        )
        try:
            demand_acquisition._ensure_lead_attribution_columns(conn)
            campaigns = core.db_fetchall(
                conn,
                """
                SELECT c.*, i.artist_name, i.studio_name,
                       (SELECT COUNT(*) FROM acquisition_visits v WHERE v.campaign_id=c.id) AS visits,
                       (SELECT COUNT(*) FROM concierge_leads l WHERE l.shop_id=c.shop_id AND l.campaign_id=c.id) AS leads
                FROM acquisition_campaigns c
                LEFT JOIN acquisition_identities i ON i.id=c.identity_id
                WHERE c.shop_id=?
                ORDER BY c.created_at DESC
                """,
                (user["shop_id"],),
            )
        except Exception:
            conn.rollback()
            campaigns = core.db_fetchall(
                conn,
                """
                SELECT c.*, i.artist_name, i.studio_name,
                       (SELECT COUNT(*) FROM acquisition_visits v WHERE v.campaign_id=c.id) AS visits,
                       0 AS leads
                FROM acquisition_campaigns c
                LEFT JOIN acquisition_identities i ON i.id=c.identity_id
                WHERE c.shop_id=?
                ORDER BY c.created_at DESC
                """,
                (user["shop_id"],),
            )
    except Exception:
        conn.rollback()
        shop, identities, campaigns = None, [], []
    finally:
        conn.close()

    campaign_rows = []
    for row in campaigns:
        campaign = dict(row)
        campaign["tracked_url"] = demand_acquisition._campaign_url(request, row)
        campaign_rows.append(campaign)

    metrics = {
        "active_campaigns": sum(1 for row in campaign_rows if row.get("status") == "active"),
        "visits": sum(int(row.get("visits") or 0) for row in campaign_rows),
        "leads": sum(int(row.get("leads") or 0) for row in campaign_rows),
        "identities": len(identities),
    }

    return core.templates.TemplateResponse(
        request=request,
        name="demand_engine.html",
        context={
            "user": user,
            "shop": shop,
            "identities": identities,
            "campaigns": campaign_rows,
            "metrics": metrics,
        },
        headers={"Cache-Control": "no-store"},
    )
