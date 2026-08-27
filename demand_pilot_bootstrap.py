"""One-click bootstrap for the Josh @ Blind Wolf zero-data demand pilot."""
import uuid

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core
import demand_acquisition

ARTIST_NAME = "Josh Daniels"
STUDIO_NAME = "Blind Wolf Tattoo"
STUDIO_ADDRESS = "50 Gaines School Rd Ste 13, Athens, GA 30605"
MINIMUM_PRICE = 100
PRICING_MODEL = "Hand-size / palm-size pricing"
STYLES = "American Traditional, Neo-Traditional"
SUBJECTS = (
    "Animals, birds, insects and moths, botanical and nature, psychedelic and whimsical imagery, "
    "dark and occult-inspired traditional, unusual remixes of classic traditional motifs"
)


def _login(request: Request):
    user, redirect = core.login_required_redirect(request)
    return user, redirect


def _find_or_create_identity(conn, shop_id):
    demand_acquisition._ensure_tables(conn)
    existing = core.db_fetchone(
        conn,
        """SELECT * FROM acquisition_identities
           WHERE owner_shop_id=? AND artist_name=? AND studio_name=? AND status='active'
           ORDER BY created_at DESC LIMIT 1""",
        (shop_id, ARTIST_NAME, STUDIO_NAME),
    )
    now = core.now_iso()
    if existing:
        core.db_execute(
            conn,
            """UPDATE acquisition_identities
               SET studio_address=?, minimum_price=?, pricing_model=?, styles=?, subjects=?, updated_at=?
               WHERE id=?""",
            (STUDIO_ADDRESS, MINIMUM_PRICE, PRICING_MODEL, STYLES, SUBJECTS, now, existing["id"]),
        )
        conn.commit()
        return existing["id"]

    identity_id = f"acq_identity_{uuid.uuid4().hex[:12]}"
    core.db_execute(
        conn,
        """INSERT INTO acquisition_identities(
            id,owner_shop_id,artist_name,studio_name,studio_address,minimum_price,
            pricing_model,styles,subjects,status,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            identity_id, shop_id, ARTIST_NAME, STUDIO_NAME, STUDIO_ADDRESS, MINIMUM_PRICE,
            PRICING_MODEL, STYLES, SUBJECTS, "active", now, now,
        ),
    )
    conn.commit()
    return identity_id


def _create_starter_campaigns(conn, shop_id, identity_id):
    identity = core.db_fetchone(conn, "SELECT * FROM acquisition_identities WHERE id=?", (identity_id,))
    now = core.now_iso()
    created = 0
    for name, hook in demand_acquisition.STARTER_CAMPAIGNS:
        existing = core.db_fetchone(
            conn,
            """SELECT id FROM acquisition_campaigns
               WHERE shop_id=? AND identity_id=? AND name=? AND channel='facebook_marketplace'""",
            (shop_id, identity_id, name),
        )
        if existing:
            continue
        title = f"{name} Tattoo Concepts — Athens"
        copy = (
            f"Original {hook.lower()} by {ARTIST_NAME}, working at {STUDIO_NAME} in Athens. "
            f"$100 minimum; pricing is based on approximate hand/palm size. "
            "Use the Tattoo Concierge to share your idea, placement, size, budget and timing and see whether it is a fit."
        )
        status, score, notes = demand_acquisition.marketplace_guard(title, copy)
        core.db_execute(
            conn,
            """INSERT INTO acquisition_campaigns(
                id,shop_id,artist_id,identity_id,name,channel,hook,status,created_at,updated_at,
                listing_title,listing_copy,compliance_status,compliance_score,compliance_notes,
                policy_version,policy_checked_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f"camp_{uuid.uuid4().hex[:12]}", shop_id, None, identity_id, name,
                "facebook_marketplace", hook, "active", now, now, title, copy,
                status, score, notes, demand_acquisition.POLICY_VERSION, now,
            ),
        )
        created += 1
    conn.commit()
    return created


@core.app.get("/demand-acquisition/bootstrap-josh-pilot", response_class=HTMLResponse)
def bootstrap_josh_pilot_page(request: Request):
    user, redirect = _login(request)
    if redirect:
        return redirect
    return HTMLResponse(
        """<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
        <title>Initialize Josh Demand Pilot</title><style>
        body{margin:0;background:#080a08;color:#f0eadf;font-family:Inter,system-ui,sans-serif}
        main{max-width:720px;margin:auto;padding:40px}section{border:1px solid #30362e;background:#0e110e;padding:24px}
        .ey{color:#d8ff45;font:700 11px monospace;letter-spacing:.15em}button{padding:13px 18px;background:#d8ff45;border:0;font-weight:900}
        a{color:#d8ff45}p{line-height:1.6;color:#b7bdb3}</style></head><body><main>
        <a href='/demand-acquisition'>← Demand Launch Console</a><section><div class='ey'>ZERO-DATA PILOT</div>
        <h1>Initialize Josh @ Blind Wolf</h1><p>This creates or updates the Josh Daniels artist acquisition identity and creates the five starter Marketplace demand experiments. It is idempotent: existing campaigns will not be duplicated.</p>
        <form method='post' action='/demand-acquisition/bootstrap-josh-pilot'><button type='submit'>Initialize pilot now</button></form>
        </section></main></body></html>""",
        headers={"Cache-Control": "no-store"},
    )


@core.app.post("/demand-acquisition/bootstrap-josh-pilot")
def bootstrap_josh_pilot(request: Request):
    user, redirect = _login(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        identity_id = _find_or_create_identity(conn, user["shop_id"])
        _create_starter_campaigns(conn, user["shop_id"], identity_id)
    finally:
        conn.close()
    return RedirectResponse("/demand-acquisition", status_code=303)
