"""App-native UI wrapper for Demand Acquisition."""
from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import demand_acquisition as acquisition

app = core.app


def _remove_route(path, method):
    method = method.upper()
    app.router.routes = [
        route for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


_remove_route("/demand-acquisition", "GET")


@app.get("/demand-acquisition", response_class=HTMLResponse)
def demand_engine_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        acquisition._ensure_tables(conn)
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
            acquisition._ensure_lead_attribution_columns(conn)
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
    finally:
        conn.close()

    total_campaigns = len(campaigns)
    active_campaigns = sum(1 for c in campaigns if c["status"] == "active")
    total_visits = sum(int(c["visits"] or 0) for c in campaigns)
    total_leads = sum(int(c["leads"] or 0) for c in campaigns)

    return core.templates.TemplateResponse(
        request=request,
        name="demand_acquisition.html",
        context={
            "user": user,
            "shop": shop,
            "identities": identities,
            "campaigns": campaigns,
            "total_campaigns": total_campaigns,
            "active_campaigns": active_campaigns,
            "total_visits": total_visits,
            "total_leads": total_leads,
        },
        headers={"Cache-Control": "no-store"},
    )
