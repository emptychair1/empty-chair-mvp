"""Make the repaired outreach pipeline the primary Hunter screen.

This preserves the working swipe discovery implementation at /owner/hunter/discover while
putting the founder ENGAGE -> DM -> REPLY -> TRIAL workflow back at /owner/hunter.
"""
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import v2_app as core
import v2_hunter_operator as hunter
import v2_hunter_crt_ui as discovery_ui
import v2_hunter_outreach as outreach


# Outreach's storage/seeding logic is repaired in v2_hunter_outreach. Replace only the
# route wiring here so the original product UX returns without reintroducing the old 500.
for route in list(core.app.router.routes):
    path = getattr(route, "path", None)
    methods = getattr(route, "methods", set()) or set()
    if path == "/owner/hunter" and "GET" in methods:
        core.app.router.routes.remove(route)
    elif path == "/owner/hunter/outreach" and "GET" in methods:
        core.app.router.routes.remove(route)
    elif path == "/owner/hunter/outreach/{account_id}" and "POST" in methods:
        core.app.router.routes.remove(route)
    elif path == "/owner/hunter/discover" and "GET" in methods:
        core.app.router.routes.remove(route)


@core.app.get("/owner/hunter/discover", response_class=HTMLResponse)
def hunter_discover(request: Request):
    hunter.admin_artist(request)
    return discovery_ui.operator_console_crt(request)


@core.app.post("/owner/hunter/outreach/{account_id}")
async def outreach_action_primary(request: Request, account_id: str):
    hunter.admin_artist(request)
    form = await request.form()
    try:
        outreach._set_stage(account_id, str(form.get("action") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/owner/hunter", status_code=303)


@core.app.get("/owner/hunter/outreach")
def outreach_alias(request: Request):
    hunter.admin_artist(request)
    return RedirectResponse("/owner/hunter", status_code=303)


@core.app.get("/owner/hunter", response_class=HTMLResponse)
def hunter_pipeline_primary(request: Request):
    hunter.admin_artist(request)
    db = core.DB()
    try:
        outreach.ensure_outreach(db)
        counts = outreach._counts(db)
        dm_today = outreach._dm_today(db)
        pending_row = db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='PENDING'"
        ).fetchone()
        pending_new = int(dict(pending_row).get("n") or 0) if pending_row else 0
        stage, target = outreach._next_action(db)
    finally:
        db.close()

    body = f"""
      <div class='pipeline-nav'>
        <a class='active' href='/owner/hunter'>OUTREACH</a>
        <a href='/owner/hunter/discover'>NEW ARTISTS ({pending_new:,})</a>
      </div>
      <p class='dim' style='margin:0 0 5px'>FOUNDER // ACQUISITION</p>
      <h1 style='margin-top:0'>HUNTER PIPELINE</h1>
      <div class='pipeline-grid'>
        <div class='pipe-stat'><b>{counts.get('ENGAGE',0):,}</b><span>TO ENGAGE</span></div>
        <div class='pipe-stat'><b>{counts.get('DM_READY',0):,}</b><span>TO DM</span></div>
        <div class='pipe-stat'><b>{counts.get('WAITING_REPLY',0):,}</b><span>WAITING REPLY</span></div>
        <div class='pipe-stat'><b>{counts.get('PAIN',0)+counts.get('INTERESTED',0):,}</b><span>LIVE OPPORTUNITIES</span></div>
        <div class='pipe-stat'><b>{counts.get('TRIAL_SENT',0):,}</b><span>TRIAL SENT</span></div>
        <div class='pipe-stat'><b>{counts.get('ACTIVATED',0):,}</b><span>ACTIVATED</span></div>
      </div>
      <div class='dm-meter'>DM SENT TODAY // <b>{dm_today:,}</b> &nbsp; TARGET // 20–30</div>
      {outreach._render_action(stage, target)}
      <p class='pipeline-note'>HUNTER STAGES THE WORK. YOU CONTROL EVERY INSTAGRAM ENGAGEMENT AND DM.</p>
    """
    return core.page(
        "Hunter Pipeline",
        body,
        script=outreach.PIPELINE_SCRIPT,
        head=outreach.PIPELINE_CSS,
    )


print("Hunter outreach primary route loaded // repaired pipeline", flush=True)
