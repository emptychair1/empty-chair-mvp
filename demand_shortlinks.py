"""Human-readable public routes for starter demand campaigns.

These routes do not add schema. They resolve a starter campaign by Josh's active
acquisition identity, record attribution through the existing /a/<campaign>
route, and keep the public URL short enough to type from Marketplace.
"""
from fastapi.responses import RedirectResponse

import app as core


SLUG_TO_CAMPAIGN = {
    "animals": "Traditional Animals",
    "weird": "Weird / Psychedelic",
    "nature": "Moths / Bugs / Nature",
    "dark": "Dark Traditional",
    "custom": "Custom Traditional",
}


def short_path_for_campaign(name: str):
    for slug, campaign_name in SLUG_TO_CAMPAIGN.items():
        if campaign_name == name:
            return f"/josh/{slug}"
    return None


@core.app.get("/josh/{slug}")
def josh_demand_shortlink(slug: str):
    campaign_name = SLUG_TO_CAMPAIGN.get((slug or "").strip().lower())
    if not campaign_name:
        return RedirectResponse("/concierge", status_code=302)

    conn = core.connect()
    try:
        campaign = core.db_fetchone(
            conn,
            """SELECT c.id
               FROM acquisition_campaigns c
               JOIN acquisition_identities i ON i.id=c.identity_id
               WHERE c.name=?
                 AND c.channel='facebook_marketplace'
                 AND c.status='active'
                 AND i.status='active'
                 AND lower(i.artist_name)=lower(?)
                 AND lower(i.studio_name)=lower(?)
               ORDER BY c.created_at DESC
               LIMIT 1""",
            (campaign_name, "Josh Daniels", "Blind Wolf Tattoo"),
        )
    except Exception:
        conn.rollback()
        campaign = None
    finally:
        conn.close()

    if not campaign:
        return RedirectResponse("/concierge", status_code=302)

    return RedirectResponse(f"/a/{campaign['id']}", status_code=302)
