"""Treat founder-marked Instagram replies as live Hunter opportunities.

Hunter cannot read arbitrary Instagram DMs automatically. This module keeps the
manual workflow explicit: when a reply arrives, the founder taps GOT REPLY and the
artist immediately moves into LIVE OPPORTUNITIES for classification.
"""
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import v2_app as core
import v2_hunter_operator as hunter
import v2_hunter_outreach as outreach
import v2_hunter_outreach_runtime_fix as runtime

REPLIED = "REPLIED"


def _reply_form(account_id: str) -> str:
    return f"""
      <form method='post' action='/owner/hunter/outreach/{quote(account_id, safe="")}' class='outreach-form'>
        <input type='hidden' name='action' value='REPLIED'>
        <button>GOT REPLY ✓</button>
      </form>
    """


def _classification_card(target: dict) -> str:
    account_id = str(target.get("account_id") or "")
    username = hunter.esc(str(target.get("username") or "").strip().lstrip("@"))
    name = hunter.esc(target.get("name") or "")
    context = " // ".join(
        hunter.esc(value)
        for value in (target.get("market"), target.get("activity_source"))
        if value
    )
    username_raw = str(target.get("username") or "").strip().lstrip("@")
    native_url, web_url = outreach._instagram_urls(username_raw)
    open_button = (
        f"<button type='button' class='outreach-open' "
        f"data-native='{hunter.esc(native_url)}' data-web='{hunter.esc(web_url)}' "
        f"onclick='openHunterInstagram(this)'>OPEN INSTAGRAM</button>"
    )
    identity = f"<div class='dim'>{name}</div>" if name and name.lower() != username.lower() else ""
    actions = (
        "<div class='outreach-actions two'>"
        + outreach._action_form(account_id, "HAS_PROBLEM", "HAS PROBLEM")
        + outreach._action_form(account_id, "INTERESTED", "INTERESTED")
        + outreach._action_form(account_id, "NO_PROBLEM", "NO PROBLEM", "quiet")
        + outreach._action_form(account_id, "NOT_INTERESTED", "NOT INTERESTED", "quiet")
        + "</div>"
    )
    return f"""
      <section class='outreach-card'>
        <div class='outreach-stage'>&gt;&gt; REPLY RECEIVED</div>
        {identity}
        <h1>@{username}</h1>
        <div class='outreach-context'>{context or 'LIVE CONVERSATION'}</div>
        {open_button}
        <p class='pipeline-note'>CLASSIFY THE REPLY SO HUNTER KNOWS WHAT TO DO NEXT.</p>
        {actions}
      </section>
    """


def _waiting_reply_card(target: dict) -> str:
    account_id = str(target.get("account_id") or "")
    username = hunter.esc(str(target.get("username") or "").strip().lstrip("@"))
    name = hunter.esc(target.get("name") or "")
    context = " // ".join(
        hunter.esc(value)
        for value in (target.get("market"), target.get("activity_source"))
        if value
    )
    username_raw = str(target.get("username") or "").strip().lstrip("@")
    native_url, web_url = outreach._instagram_urls(username_raw)
    open_button = (
        f"<button type='button' class='outreach-open' "
        f"data-native='{hunter.esc(native_url)}' data-web='{hunter.esc(web_url)}' "
        f"onclick='openHunterInstagram(this)'>OPEN INSTAGRAM</button>"
    )
    identity = f"<div class='dim'>{name}</div>" if name and name.lower() != username.lower() else ""
    return f"""
      <section class='outreach-card'>
        <div class='outreach-stage'>&gt;&gt; CHECK REPLY</div>
        {identity}
        <h1>@{username}</h1>
        <div class='outreach-context'>{context or 'DM SENT // WAITING FOR RESPONSE'}</div>
        {open_button}
        {_reply_form(account_id)}
        <p class='pipeline-note'>NO REPLY YET? LEAVE THEM HERE. GOT ONE? TAP GOT REPLY.</p>
      </section>
    """


def render_action(stage: str, target: dict | None) -> str:
    if stage == REPLIED and target:
        return _classification_card(target)
    if stage == "WAITING_REPLY" and target:
        return _waiting_reply_card(target)
    return outreach._render_action(stage, target)


def counts(db: core.DB) -> dict[str, int]:
    stages = ("ENGAGE", "DM_READY", "WAITING_REPLY", REPLIED, "PAIN", "INTERESTED", "TRIAL_SENT", "ACTIVATED", "CLOSED")
    result = {stage: 0 for stage in stages}
    for row in db.execute(f"SELECT stage,COUNT(*) AS n FROM {runtime.TABLE} GROUP BY stage").fetchall():
        item = dict(row)
        stage = str(item.get("stage") or "")
        if stage in result:
            result[stage] = int(item.get("n") or 0)
    return result


def next_action(db: core.DB):
    for stage in ("INTERESTED", "PAIN", REPLIED, "DM_READY", "ENGAGE", "WAITING_REPLY", "TRIAL_SENT"):
        target = runtime.target_for_stage(db, stage)
        if target:
            return stage, target
    return "DONE", None


def mark_replied(account_id: str) -> None:
    db = core.DB()
    try:
        runtime.ensure_runtime_outreach(db)
        row = db.execute(f"SELECT account_id FROM {runtime.TABLE} WHERE account_id=?", (account_id,)).fetchone()
        if not row:
            raise ValueError("outreach artist not found")
        stamp = hunter.now()
        db.execute(
            f"UPDATE {runtime.TABLE} SET stage=?,replied_at=?,updated_at=? WHERE account_id=?",
            (REPLIED, stamp, stamp, account_id),
        )
        db.commit()
    except Exception:
        db.raw.rollback()
        raise
    finally:
        db.close()


# Replace only the primary outreach routes after the runtime fix has loaded.
for route in list(core.app.router.routes):
    path = getattr(route, "path", None)
    methods = getattr(route, "methods", set()) or set()
    if path == "/owner/hunter" and "GET" in methods:
        core.app.router.routes.remove(route)
    elif path == "/owner/hunter/outreach/{account_id}" and "POST" in methods:
        core.app.router.routes.remove(route)
    elif path == "/owner/hunter/outreach" and "GET" in methods:
        core.app.router.routes.remove(route)


@core.app.post("/owner/hunter/outreach/{account_id}")
async def outreach_action_reply_aware(request: Request, account_id: str):
    hunter.admin_artist(request)
    form = await request.form()
    action = str(form.get("action") or "").upper()
    try:
        if action == "REPLIED":
            mark_replied(account_id)
        else:
            runtime.set_stage(account_id, action)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/owner/hunter", status_code=303)


@core.app.get("/owner/hunter/outreach")
def outreach_alias_reply_aware(request: Request):
    hunter.admin_artist(request)
    return RedirectResponse("/owner/hunter", status_code=303)


@core.app.get("/owner/hunter", response_class=HTMLResponse)
def hunter_pipeline_reply_aware(request: Request):
    hunter.admin_artist(request)
    db = core.DB()
    try:
        runtime.ensure_runtime_outreach(db)
        stage_counts = counts(db)
        sent_today = runtime.dm_today(db)
        pending_row = db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='PENDING'"
        ).fetchone()
        pending_new = int(dict(pending_row).get("n") or 0) if pending_row else 0
        stage, target = next_action(db)
    finally:
        db.close()

    live = stage_counts.get(REPLIED, 0) + stage_counts.get("PAIN", 0) + stage_counts.get("INTERESTED", 0)
    body = f"""
      <div class='pipeline-nav'>
        <a class='active' href='/owner/hunter'>OUTREACH</a>
        <a href='/owner/hunter/discover'>NEW ARTISTS ({pending_new:,})</a>
      </div>
      <p class='dim' style='margin:0 0 5px'>FOUNDER // ACQUISITION</p>
      <h1 style='margin-top:0'>HUNTER PIPELINE</h1>
      <div class='pipeline-grid'>
        <div class='pipe-stat'><b>{stage_counts.get('ENGAGE',0):,}</b><span>TO ENGAGE</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('DM_READY',0):,}</b><span>TO DM</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('WAITING_REPLY',0):,}</b><span>WAITING REPLY</span></div>
        <div class='pipe-stat'><b>{live:,}</b><span>LIVE OPPORTUNITIES</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('TRIAL_SENT',0):,}</b><span>TRIAL SENT</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('ACTIVATED',0):,}</b><span>ACTIVATED</span></div>
      </div>
      <div class='dm-meter'>DM SENT TODAY // <b>{sent_today:,}</b> &nbsp; TARGET // 20–30</div>
      {render_action(stage, target)}
      <p class='pipeline-note'>HUNTER STAGES THE WORK. YOU CONTROL EVERY INSTAGRAM ENGAGEMENT AND DM.</p>
    """
    return core.page(
        "Hunter Pipeline",
        body,
        script=outreach.PIPELINE_SCRIPT,
        head=outreach.PIPELINE_CSS,
    )


print("Hunter reply opportunity tracking loaded", flush=True)
