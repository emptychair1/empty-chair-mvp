"""Additional free acquisition channels for Demand Engine starter campaigns."""
import uuid

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core
import demand_acquisition


CHANNELS = {
    "facebook_marketplace": "Facebook Marketplace",
    "facebook_group": "Facebook Group",
    "facebook_profile": "Facebook Profile",
    "instagram_post": "Instagram Post",
    "instagram_reel": "Instagram Reel",
    "instagram_story": "Instagram Story",
    "reddit": "Reddit",
    "tiktok": "TikTok",
    "referral": "Referral / Direct Share",
    "qr": "QR / Physical",
}


@core.app.post("/demand-acquisition/channel-set")
def create_channel_starter_set(
    request: Request,
    identity_id: str = Form(...),
    channel: str = Form(...),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    channel = channel.strip()
    if channel not in CHANNELS:
        return HTMLResponse("Unsupported acquisition channel.", status_code=400)

    identity_id = identity_id.strip()
    now = core.now_iso()
    conn = core.connect()
    try:
        demand_acquisition._ensure_tables(conn)
        identity = core.db_fetchone(
            conn,
            "SELECT id FROM acquisition_identities WHERE id=? AND owner_shop_id=? AND status='active'",
            (identity_id, user["shop_id"]),
        )
        if not identity:
            return HTMLResponse("Invalid artist acquisition identity.", status_code=400)

        for name, hook in demand_acquisition.STARTER_CAMPAIGNS:
            existing = core.db_fetchone(
                conn,
                "SELECT id FROM acquisition_campaigns WHERE shop_id=? AND identity_id=? AND name=? AND channel=?",
                (user["shop_id"], identity_id, name, channel),
            )
            if existing:
                continue
            core.db_execute(
                conn,
                "INSERT INTO acquisition_campaigns(id,shop_id,artist_id,identity_id,name,channel,hook,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    f"camp_{uuid.uuid4().hex[:12]}",
                    user["shop_id"],
                    None,
                    identity_id,
                    name,
                    channel,
                    hook,
                    "active",
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/demand-acquisition", status_code=303)
