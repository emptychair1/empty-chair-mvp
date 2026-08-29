"""Public Tattoo Finder acquisition strategy for Demand Engine."""
from fastapi import Form, Request
from fastapi.responses import HTMLResponse

import app as core
import concierge_leads
import demand_acquisition


def _identity_for_market(conn, market: str):
    demand_acquisition._ensure_tables(conn)
    market_like = f"%{market.strip()}%"
    return core.db_fetchone(conn, """
        SELECT * FROM acquisition_identities
        WHERE status='active' AND studio_address LIKE ?
        ORDER BY created_at DESC LIMIT 1
    """, (market_like,))


def _campaign_for_identity(conn, identity_id: str):
    return core.db_fetchone(conn, """
        SELECT * FROM acquisition_campaigns
        WHERE identity_id=? AND status='active'
        ORDER BY created_at DESC LIMIT 1
    """, (identity_id,))


@core.app.get("/tattoo-finder/{market}", response_class=HTMLResponse)
def tattoo_finder(request: Request, market: str):
    conn = core.connect()
    try:
        identity = _identity_for_market(conn, market)
        if not identity:
            return core.templates.TemplateResponse(request=request, name="tattoo_finder.html", context={"market": market.title(), "identity": None, "campaign": None, "error": "Tattoo Finder is not live in this market yet."}, status_code=404)
        campaign = _campaign_for_identity(conn, identity["id"])
        return core.templates.TemplateResponse(request=request, name="tattoo_finder.html", context={"market": market.title(), "identity": identity, "campaign": campaign, "error": None}, headers={"Cache-Control": "no-store"})
    finally:
        conn.close()


@core.app.post("/tattoo-finder/{market}", response_class=HTMLResponse)
def tattoo_finder_submit(request: Request, market: str, project: str = Form(...), placement: str = Form(...), size: str = Form(...), styles: str = Form(""), budget: str = Form(...), timing: str = Form(...), name: str = Form(...), phone: str = Form(...), email: str = Form(""), offer_opt_in: str = Form("")):
    conn = core.connect()
    try:
        identity = _identity_for_market(conn, market)
        if not identity:
            return HTMLResponse("Tattoo Finder is not live in this market yet.", status_code=404)
        campaign = _campaign_for_identity(conn, identity["id"])
    finally:
        conn.close()

    profile = {
        "project": project.strip(), "placement": placement.strip(), "size": size.strip(),
        "styles": styles.strip(), "budget": budget.strip(), "timing": timing.strip(),
        "name": name.strip(), "phone": phone.strip(), "email": email.strip().lower(),
        "offer_opt_in": offer_opt_in == "on", "artist_vibe": "",
        "acquisition_mode": "tattoo_finder", "market": market.strip().lower(),
    }
    required = ("project", "placement", "size", "budget", "timing", "name", "phone")
    if any(not profile[key] for key in required):
        return HTMLResponse("Please complete all required Tattoo Finder fields.", status_code=400)

    _customer_id, lead_id = concierge_leads.save_concierge_profile(identity["owner_shop_id"], profile, 0)
    source = (request.query_params.get("src") or "tattoo_finder").strip()[:80]
    campaign_id = request.query_params.get("campaign_id") or (campaign["id"] if campaign else None)
    attribution_conn = core.connect()
    try:
        demand_acquisition.record_lead_attribution(attribution_conn, lead_id, campaign_id, source)
    finally:
        attribution_conn.close()

    core.event("demand.tattoo_finder.lead", "concierge_lead", lead_id)
    return core.templates.TemplateResponse(request=request, name="tattoo_finder_complete.html", context={"market": market.title(), "identity": identity, "lead_id": lead_id}, headers={"Cache-Control": "no-store"})
