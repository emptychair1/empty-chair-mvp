"""Runtime-safe Hunter routing: Watchtower, New Artists, and Outreach are distinct."""
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import v2_app as core
import v2_hunter_operator as hunter
import v2_hunter_outreach as outreach
import v2_hunter_crt_ui as lead_ui

TABLE = "hunter_outreach_v2"
CREATE_TABLE = f"""CREATE TABLE IF NOT EXISTS {TABLE} (
    account_id TEXT PRIMARY KEY,
    stage TEXT NOT NULL DEFAULT 'ENGAGE',
    outcome TEXT,
    followed_at TEXT,
    engaged_at TEXT,
    dm_sent_at TEXT,
    replied_at TEXT,
    trial_sent_at TEXT,
    activated_at TEXT,
    updated_at TEXT NOT NULL
)"""
STAGES = ("ENGAGE", "DM_READY", "WAITING_REPLY", "PAIN", "INTERESTED", "TRIAL_SENT", "ACTIVATED", "CLOSED")
ACTIONS = outreach.ACTIONS

NAV_CSS = """
<style>
.hunter-section-nav{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin:0 0 22px}.hunter-section-nav a{border:1px solid var(--off);padding:10px 5px;text-align:center;text-decoration:none;color:var(--dim);font-size:9px;letter-spacing:.05em;white-space:nowrap}.hunter-section-nav a.active{border-color:var(--amber);color:var(--bright);box-shadow:0 0 14px rgba(255,176,0,.09)}
</style>
"""


def ensure_runtime_outreach(db: core.DB) -> None:
    hunter.ensure_tables(db)
    db.execute(CREATE_TABLE)
    db.commit()
    existing = {str(dict(r).get("account_id") or "") for r in db.execute(f"SELECT account_id FROM {TABLE}").fetchall()}
    handled = db.execute("SELECT account_id,decided_at,last_ingested_at FROM hunter_operator_targets WHERE decision='HANDLED' AND account_id IS NOT NULL").fetchall()
    stamp = hunter.now(); changed = False
    for row in handled:
        item = dict(row); account_id = str(item.get("account_id") or "")
        if not account_id or account_id in existing: continue
        db.execute(f"INSERT INTO {TABLE}(account_id,stage,followed_at,updated_at) VALUES(?,?,?,?)", (account_id,"ENGAGE",item.get("decided_at") or item.get("last_ingested_at") or stamp,stamp))
        existing.add(account_id); changed = True
    if changed: db.commit()


def counts(db: core.DB) -> dict[str, int]:
    result = {stage: 0 for stage in STAGES}
    for row in db.execute(f"SELECT stage,COUNT(*) AS n FROM {TABLE} GROUP BY stage").fetchall():
        item = dict(row); stage = str(item.get("stage") or "")
        if stage in result: result[stage] = int(item.get("n") or 0)
    return result


def dm_today(db: core.DB) -> int:
    row = db.execute(f"SELECT COUNT(*) AS n FROM {TABLE} WHERE dm_sent_at LIKE ?", (hunter._today_prefix()+"%",)).fetchone()
    return int(dict(row).get("n") or 0) if row else 0


def pending_new_count() -> int:
    db = core.DB()
    try:
        hunter.ensure_tables(db)
        row = db.execute("SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='PENDING'").fetchone()
        return int(dict(row).get("n") or 0) if row else 0
    finally:
        db.close()


def target_for_stage(db: core.DB, stage: str):
    row = db.execute(f"""SELECT o.account_id,o.stage,o.outcome,o.followed_at,o.engaged_at,o.dm_sent_at,o.replied_at,o.trial_sent_at,o.activated_at,o.updated_at,t.username,t.profile_url,t.snapshot_json,t.score FROM {TABLE} o JOIN hunter_operator_targets t ON t.account_id=o.account_id WHERE o.stage=? ORDER BY o.updated_at ASC,t.score DESC,t.username ASC LIMIT 1""", (stage,)).fetchone()
    if not row: return None
    item = dict(row); snap = hunter.load_json(item.get("snapshot_json"), {})
    if isinstance(snap, dict):
        item["name"] = snap.get("name"); item["market"] = snap.get("market"); item["activity_source"] = snap.get("activity_source")
    return item


def next_action(db: core.DB):
    for stage in ("INTERESTED","PAIN","DM_READY","ENGAGE","WAITING_REPLY","TRIAL_SENT"):
        target = target_for_stage(db, stage)
        if target: return stage, target
    return "DONE", None


def set_stage(account_id: str, action: str) -> None:
    action = str(action or "").upper()
    if action not in ACTIONS: raise ValueError("invalid outreach action")
    db = core.DB()
    try:
        ensure_runtime_outreach(db)
        row = db.execute(f"SELECT * FROM {TABLE} WHERE account_id=?", (account_id,)).fetchone()
        if not row: raise ValueError("outreach artist not found")
        current = dict(row); stamp = hunter.now(); updates = {"updated_at": stamp}
        if action == "ENGAGED": updates.update(stage="DM_READY", engaged_at=stamp)
        elif action == "DM_SENT": updates.update(stage="WAITING_REPLY", dm_sent_at=stamp)
        elif action == "HAS_PROBLEM": updates.update(stage="PAIN", outcome="HAS_PROBLEM", replied_at=stamp)
        elif action == "INTERESTED": updates.update(stage="INTERESTED", outcome="INTERESTED", replied_at=current.get("replied_at") or stamp)
        elif action == "NO_PROBLEM": updates.update(stage="CLOSED", outcome="NO_PROBLEM", replied_at=stamp)
        elif action == "NOT_INTERESTED": updates.update(stage="CLOSED", outcome="NOT_INTERESTED", replied_at=current.get("replied_at") or stamp)
        elif action == "TRIAL_SENT": updates.update(stage="TRIAL_SENT", trial_sent_at=stamp)
        elif action == "ACTIVATED": updates.update(stage="ACTIVATED", activated_at=stamp)
        elif action == "CLOSE": updates.update(stage="CLOSED", outcome=current.get("outcome") or "CLOSED")
        cols = ",".join(f"{k}=?" for k in updates)
        db.execute(f"UPDATE {TABLE} SET {cols} WHERE account_id=?", tuple(updates.values())+(account_id,)); db.commit()
    except Exception:
        db.raw.rollback(); raise
    finally: db.close()


def section_nav(active: str, pending_new: int | None = None) -> str:
    pending = pending_new_count() if pending_new is None else pending_new
    def item(key: str, href: str, label: str) -> str:
        cls = "active" if active == key else ""
        return f"<a class='{cls}' href='{href}'>{label}</a>"
    return (
        NAV_CSS + "<div class='hunter-section-nav'>" +
        item("watchtower", "/owner/hunter/watchtower", "WATCHTOWER") +
        item("new", "/owner/hunter/new-artists", f"NEW ARTISTS ({pending:,})") +
        item("outreach", "/owner/hunter/outreach", "OUTREACH") +
        "</div>"
    )


def decorate_page(response: HTMLResponse, active: str, pending_new: int | None = None) -> HTMLResponse:
    try:
        doc = response.body.decode("utf-8")
        nav = section_nav(active, pending_new)
        marker = "</header>"
        doc = doc.replace(marker, marker + nav, 1) if marker in doc else nav + doc
        return HTMLResponse(doc, status_code=response.status_code, headers={"Cache-Control":"no-store"})
    except Exception:
        return response


# Final route ownership. These are deliberately three different product surfaces.
for route in list(core.app.router.routes):
    path = getattr(route,"path",None); methods = getattr(route,"methods",set()) or set()
    if path in {"/owner/hunter","/owner/hunter/watchtower","/owner/hunter/outreach","/owner/hunter/discover","/owner/hunter/discovery","/owner/hunter/new","/owner/hunter/new-artists"} and "GET" in methods:
        core.app.router.routes.remove(route)
    elif path in {"/owner/hunter/outreach/{account_id}", "/owner/hunter/{account_id}/decision", "/owner/hunter/bulk"} and "POST" in methods:
        core.app.router.routes.remove(route)


@core.app.get("/owner/hunter", response_class=HTMLResponse)
@core.app.get("/owner/hunter/watchtower", response_class=HTMLResponse)
def hunter_watchtower_runtime(request: Request):
    response = lead_ui.hunter_command_center(request)
    return decorate_page(response, "watchtower")


@core.app.get("/owner/hunter/new-artists", response_class=HTMLResponse)
def hunter_new_artists_runtime(request: Request):
    hunter.admin_artist(request)
    response = hunter.operator_console(request)
    return decorate_page(response, "new")


@core.app.get("/owner/hunter/discover")
@core.app.get("/owner/hunter/discovery")
@core.app.get("/owner/hunter/new")
def hunter_discovery_compat(request: Request):
    hunter.admin_artist(request)
    return RedirectResponse("/owner/hunter/new-artists", status_code=303)


@core.app.post("/owner/hunter/{account_id}/decision")
async def hunter_new_artist_decision_runtime(request: Request, account_id: str):
    artist = hunter.admin_artist(request)
    form = await request.form()
    try:
        changed = hunter.set_decision(account_id, str(form.get("decision") or ""), artist["email"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not changed: raise HTTPException(404, "Target not found")
    return RedirectResponse("/owner/hunter/new-artists", status_code=303)


@core.app.post("/owner/hunter/bulk")
async def hunter_new_artist_bulk_runtime(request: Request):
    artist = hunter.admin_artist(request)
    form = await request.form()
    account_ids = [str(value) for value in form.getlist("account_id") if str(value)]
    if len(account_ids) > 200: raise HTTPException(400, "Bulk review limit is 200")
    for account_id in account_ids:
        hunter.set_decision(account_id, str(form.get("decision") or ""), artist["email"], bulk=True)
    return RedirectResponse("/owner/hunter/new-artists", status_code=303)


@core.app.post("/owner/hunter/outreach/{account_id}")
async def outreach_action_runtime(request: Request, account_id: str):
    hunter.admin_artist(request); form = await request.form()
    try: set_stage(account_id, str(form.get("action") or ""))
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/owner/hunter/outreach", status_code=303)


@core.app.get("/owner/hunter/outreach", response_class=HTMLResponse)
def hunter_outreach_runtime(request: Request):
    hunter.admin_artist(request); db = core.DB()
    try:
        ensure_runtime_outreach(db); stage_counts = counts(db); sent_today = dm_today(db)
        pending_row = db.execute("SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='PENDING'").fetchone()
        pending_new = int(dict(pending_row).get("n") or 0) if pending_row else 0
        stage, target = next_action(db)
    finally: db.close()
    body = f"""
      {section_nav('outreach', pending_new)}
      <p class='dim' style='margin:0 0 5px'>FOUNDER // ACQUISITION</p>
      <h1 style='margin-top:0'>HUNTER OUTREACH</h1>
      <div class='pipeline-grid'>
        <div class='pipe-stat'><b>{stage_counts.get('ENGAGE',0):,}</b><span>TO ENGAGE</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('DM_READY',0):,}</b><span>TO DM</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('WAITING_REPLY',0):,}</b><span>WAITING REPLY</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('PAIN',0)+stage_counts.get('INTERESTED',0):,}</b><span>LIVE OPPORTUNITIES</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('TRIAL_SENT',0):,}</b><span>TRIAL SENT</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('ACTIVATED',0):,}</b><span>ACTIVATED</span></div>
      </div>
      <div class='dm-meter'>DM SENT TODAY // <b>{sent_today:,}</b> &nbsp; TARGET // 20–30</div>
      {outreach._render_action(stage,target)}
      <p class='pipeline-note'>HUNTER STAGES THE WORK. YOU CONTROL EVERY INSTAGRAM ENGAGEMENT AND DM.</p>
    """
    return core.page("Hunter Outreach", body, script=outreach.PIPELINE_SCRIPT, head=outreach.PIPELINE_CSS)


print("Hunter route repair loaded // Watchtower + New Artists + Outreach", flush=True)
