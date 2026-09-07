"""Runtime-safe primary Hunter outreach pipeline.

Keeps the requested Hunter UX while isolating outreach state from the failed first
production table. Discovery remains at /owner/hunter/discover.
"""
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import v2_app as core
import v2_hunter_operator as hunter
import v2_hunter_outreach as outreach

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

STAGES = (
    "ENGAGE", "DM_READY", "WAITING_REPLY", "PAIN", "INTERESTED",
    "TRIAL_SENT", "ACTIVATED", "CLOSED",
)
ACTIONS = outreach.ACTIONS


def ensure_runtime_outreach(db: core.DB) -> None:
    """Create a clean outreach state table and seed followed artists idempotently."""
    hunter.ensure_tables(db)
    db.execute(CREATE_TABLE)
    db.commit()

    existing = {
        str(dict(row).get("account_id") or "")
        for row in db.execute(f"SELECT account_id FROM {TABLE}").fetchall()
    }
    handled = db.execute(
        """SELECT account_id,decided_at,last_ingested_at
           FROM hunter_operator_targets
           WHERE decision='HANDLED' AND account_id IS NOT NULL"""
    ).fetchall()
    stamp = hunter.now()
    changed = False
    for row in handled:
        item = dict(row)
        account_id = str(item.get("account_id") or "")
        if not account_id or account_id in existing:
            continue
        db.execute(
            f"""INSERT INTO {TABLE}
                (account_id,stage,followed_at,updated_at)
                VALUES(?,?,?,?)""",
            (
                account_id,
                "ENGAGE",
                item.get("decided_at") or item.get("last_ingested_at") or stamp,
                stamp,
            ),
        )
        existing.add(account_id)
        changed = True
    if changed:
        db.commit()


def counts(db: core.DB) -> dict[str, int]:
    result = {stage: 0 for stage in STAGES}
    for row in db.execute(f"SELECT stage,COUNT(*) AS n FROM {TABLE} GROUP BY stage").fetchall():
        item = dict(row)
        stage = str(item.get("stage") or "")
        if stage in result:
            result[stage] = int(item.get("n") or 0)
    return result


def dm_today(db: core.DB) -> int:
    row = db.execute(
        f"SELECT COUNT(*) AS n FROM {TABLE} WHERE dm_sent_at LIKE ?",
        (hunter._today_prefix() + "%",),
    ).fetchone()
    return int(dict(row).get("n") or 0) if row else 0


def target_for_stage(db: core.DB, stage: str):
    row = db.execute(
        f"""SELECT o.account_id,o.stage,o.outcome,o.followed_at,o.engaged_at,
                   o.dm_sent_at,o.replied_at,o.trial_sent_at,o.activated_at,o.updated_at,
                   t.username,t.profile_url,t.snapshot_json,t.score
            FROM {TABLE} o
            JOIN hunter_operator_targets t ON t.account_id=o.account_id
            WHERE o.stage=?
            ORDER BY o.updated_at ASC,t.score DESC,t.username ASC
            LIMIT 1""",
        (stage,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    snap = hunter.load_json(item.get("snapshot_json"), {})
    if isinstance(snap, dict):
        item["name"] = snap.get("name")
        item["market"] = snap.get("market")
        item["activity_source"] = snap.get("activity_source")
    return item


def next_action(db: core.DB):
    for stage in ("INTERESTED", "PAIN", "DM_READY", "ENGAGE", "WAITING_REPLY", "TRIAL_SENT"):
        target = target_for_stage(db, stage)
        if target:
            return stage, target
    return "DONE", None


def set_stage(account_id: str, action: str) -> None:
    action = str(action or "").upper()
    if action not in ACTIONS:
        raise ValueError("invalid outreach action")
    db = core.DB()
    try:
        ensure_runtime_outreach(db)
        row = db.execute(f"SELECT * FROM {TABLE} WHERE account_id=?", (account_id,)).fetchone()
        if not row:
            raise ValueError("outreach artist not found")
        current = dict(row)
        stamp = hunter.now()
        updates = {"updated_at": stamp}
        if action == "ENGAGED":
            updates.update(stage="DM_READY", engaged_at=stamp)
        elif action == "DM_SENT":
            updates.update(stage="WAITING_REPLY", dm_sent_at=stamp)
        elif action == "HAS_PROBLEM":
            updates.update(stage="PAIN", outcome="HAS_PROBLEM", replied_at=stamp)
        elif action == "INTERESTED":
            updates.update(stage="INTERESTED", outcome="INTERESTED", replied_at=current.get("replied_at") or stamp)
        elif action == "NO_PROBLEM":
            updates.update(stage="CLOSED", outcome="NO_PROBLEM", replied_at=stamp)
        elif action == "NOT_INTERESTED":
            updates.update(stage="CLOSED", outcome="NOT_INTERESTED", replied_at=current.get("replied_at") or stamp)
        elif action == "TRIAL_SENT":
            updates.update(stage="TRIAL_SENT", trial_sent_at=stamp)
        elif action == "ACTIVATED":
            updates.update(stage="ACTIVATED", activated_at=stamp)
        elif action == "CLOSE":
            updates.update(stage="CLOSED", outcome=current.get("outcome") or "CLOSED")
        cols = ",".join(f"{key}=?" for key in updates)
        db.execute(
            f"UPDATE {TABLE} SET {cols} WHERE account_id=?",
            tuple(updates.values()) + (account_id,),
        )
        db.commit()
    except Exception:
        db.raw.rollback()
        raise
    finally:
        db.close()


# Replace only the broken outreach primary routes. Discovery stays untouched.
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
async def outreach_action_runtime(request: Request, account_id: str):
    hunter.admin_artist(request)
    form = await request.form()
    try:
        set_stage(account_id, str(form.get("action") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/owner/hunter", status_code=303)


@core.app.get("/owner/hunter/outreach")
def outreach_alias_runtime(request: Request):
    hunter.admin_artist(request)
    return RedirectResponse("/owner/hunter", status_code=303)


@core.app.get("/owner/hunter", response_class=HTMLResponse)
def hunter_pipeline_runtime(request: Request):
    hunter.admin_artist(request)
    db = core.DB()
    try:
        ensure_runtime_outreach(db)
        stage_counts = counts(db)
        sent_today = dm_today(db)
        pending_row = db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='PENDING'"
        ).fetchone()
        pending_new = int(dict(pending_row).get("n") or 0) if pending_row else 0
        stage, target = next_action(db)
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
        <div class='pipe-stat'><b>{stage_counts.get('ENGAGE',0):,}</b><span>TO ENGAGE</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('DM_READY',0):,}</b><span>TO DM</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('WAITING_REPLY',0):,}</b><span>WAITING REPLY</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('PAIN',0)+stage_counts.get('INTERESTED',0):,}</b><span>LIVE OPPORTUNITIES</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('TRIAL_SENT',0):,}</b><span>TRIAL SENT</span></div>
        <div class='pipe-stat'><b>{stage_counts.get('ACTIVATED',0):,}</b><span>ACTIVATED</span></div>
      </div>
      <div class='dm-meter'>DM SENT TODAY // <b>{sent_today:,}</b> &nbsp; TARGET // 20–30</div>
      {outreach._render_action(stage, target)}
      <p class='pipeline-note'>HUNTER STAGES THE WORK. YOU CONTROL EVERY INSTAGRAM ENGAGEMENT AND DM.</p>
    """
    return core.page(
        "Hunter Pipeline",
        body,
        script=outreach.PIPELINE_SCRIPT,
        head=outreach.PIPELINE_CSS,
    )


print("Hunter outreach runtime fix loaded // primary pipeline v2 state", flush=True)
