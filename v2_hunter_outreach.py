"""Founder-only Hunter outreach pipeline.

Turns followed Hunter artists into a manual, trackable founder-led sales workflow:
FOLLOWED -> ENGAGE -> DM READY -> WAITING REPLY -> PAIN / INTERESTED -> TRIAL -> ACTIVATED.
No Instagram follow or DM is automated; the app only stages the next human action.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import v2_app as core
import v2_hunter_operator as hunter
import v2_hunter_crt_ui as discovery_ui


OUTREACH_TABLE = """CREATE TABLE IF NOT EXISTS hunter_outreach (
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

STAGES = {
    "ENGAGE", "DM_READY", "WAITING_REPLY", "PAIN", "INTERESTED",
    "TRIAL_SENT", "ACTIVATED", "CLOSED",
}
ACTIONS = {
    "ENGAGED", "DM_SENT", "HAS_PROBLEM", "INTERESTED", "NO_PROBLEM",
    "NOT_INTERESTED", "TRIAL_SENT", "ACTIVATED", "CLOSE",
}

OPENING_DM = "Hey — random question. When you get a same-week cancellation, what do you usually do to try to fill it?"
PAIN_DM = "That’s exactly why I built Empty Chair. It automatically works through your existing clients when a cancellation hits instead of you having to scramble and post everywhere. I’m giving artists 7 days free right now if you want to try it."
TRIAL_DM = "Here you go — 7 days free, no card required: https://tryemptychair.com"


def ensure_outreach(db: core.DB) -> None:
    hunter.ensure_tables(db)
    db.execute(OUTREACH_TABLE)
    stamp = hunter.now()
    # Every HANDLED Hunter target represents a founder follow/review intent. Seed it into
    # outreach once and never reset its later pipeline state on re-ingest.
    db.execute(
        """INSERT INTO hunter_outreach(account_id,stage,followed_at,updated_at)
           SELECT account_id,'ENGAGE',COALESCE(decided_at,last_ingested_at),?
           FROM hunter_operator_targets
           WHERE decision='HANDLED'
           ON CONFLICT(account_id) DO NOTHING""",
        (stamp,),
    )
    db.commit()


def _set_stage(account_id: str, action: str) -> None:
    action = str(action or "").upper()
    if action not in ACTIONS:
        raise ValueError("invalid outreach action")
    db = core.DB()
    try:
        ensure_outreach(db)
        row = db.execute("SELECT * FROM hunter_outreach WHERE account_id=?", (account_id,)).fetchone()
        if not row:
            raise ValueError("outreach artist not found")
        current = dict(row)
        stamp = hunter.now()
        updates: dict[str, object] = {"updated_at": stamp}
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
        db.execute(f"UPDATE hunter_outreach SET {cols} WHERE account_id=?", tuple(updates.values()) + (account_id,))
        db.commit()
    except Exception:
        db.raw.rollback()
        raise
    finally:
        db.close()


def _counts(db: core.DB) -> dict[str, int]:
    rows = db.execute("SELECT stage,COUNT(*) AS n FROM hunter_outreach GROUP BY stage").fetchall()
    counts = {stage: 0 for stage in STAGES}
    for row in rows:
        item = dict(row)
        counts[str(item.get("stage") or "")] = int(item.get("n") or 0)
    return counts


def _dm_today(db: core.DB) -> int:
    prefix = hunter._today_prefix()
    row = db.execute("SELECT COUNT(*) AS n FROM hunter_outreach WHERE dm_sent_at LIKE ?", (prefix + "%",)).fetchone()
    return int(dict(row).get("n") or 0)


def _target_for_stage(db: core.DB, stage: str) -> dict | None:
    row = db.execute(
        """SELECT o.*,t.username,t.profile_url,t.snapshot_json,t.score
           FROM hunter_outreach o
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
        for key in ("name", "market", "activity_source"):
            item[key] = snap.get(key) or item.get(key)
    return item


def _waiting_target(db: core.DB) -> dict | None:
    return _target_for_stage(db, "WAITING_REPLY")


def _next_action(db: core.DB) -> tuple[str, dict | None]:
    # Highest-value founder actions first, then normal daily cadence.
    for stage in ("INTERESTED", "PAIN", "DM_READY", "ENGAGE", "WAITING_REPLY", "TRIAL_SENT"):
        target = _target_for_stage(db, stage)
        if target:
            return stage, target
    return "DONE", None


def _instagram_urls(username: str) -> tuple[str, str]:
    encoded = quote(username.strip().lstrip("@"), safe="._")
    return f"instagram://user?username={encoded}", f"https://www.instagram.com/_u/{encoded}/"


def _copy_block(text: str, label: str) -> str:
    safe = hunter.esc(text)
    return f"""
      <div class='outreach-copy'>
        <div class='outreach-copy-label'>{hunter.esc(label)}</div>
        <div class='outreach-message' id='outreach-message'>{safe}</div>
        <button type='button' class='quiet' onclick='copyHunterMessage()'>COPY MESSAGE</button>
      </div>
    """


def _action_form(account_id: str, action: str, label: str, css: str = "") -> str:
    path_id = quote(account_id, safe="")
    return f"""
      <form method='post' action='/owner/hunter/outreach/{path_id}' class='outreach-form'>
        <input type='hidden' name='action' value='{hunter.esc(action)}'>
        <button class='{hunter.esc(css)}'>{hunter.esc(label)}</button>
      </form>
    """


PIPELINE_CSS = """
<style>
.pipeline-nav{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:0 0 22px}.pipeline-nav a{padding:12px;border:1px solid var(--off);text-decoration:none;text-align:center}.pipeline-nav .active{border-color:var(--amber);background:var(--off)}
.pipeline-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:18px 0 26px}.pipe-stat{border:1px solid var(--off);padding:12px}.pipe-stat b{display:block;color:var(--bright);font-size:25px;font-weight:400}.pipe-stat span{color:var(--dim);font-size:10px;letter-spacing:.08em}
.outreach-card{border:1px solid var(--off);border-radius:18px;padding:24px 20px;margin-top:14px}.outreach-card h1{font-size:29px;color:var(--bright);overflow-wrap:anywhere;margin:5px 0 8px}.outreach-stage{font-size:11px;letter-spacing:.14em;color:var(--amber)}.outreach-context{font-size:11px;color:var(--dim);line-height:1.5;margin-bottom:18px}
.outreach-copy{border-top:1px dotted var(--off);border-bottom:1px dotted var(--off);padding:16px 0;margin:18px 0}.outreach-copy-label{font-size:10px;color:var(--dim);margin-bottom:10px}.outreach-message{color:var(--bright);line-height:1.55;margin-bottom:13px;white-space:pre-wrap}.outreach-actions{display:grid;gap:9px}.outreach-actions.two{grid-template-columns:1fr 1fr}.outreach-form{margin:0}.outreach-open{margin:10px 0}.pipeline-note{font-size:10px;color:var(--dim);line-height:1.5;text-align:center;margin-top:14px}.dm-meter{margin:0 0 18px;padding:10px 0;border-bottom:1px dotted var(--off);font-size:11px;color:var(--dim)}.dm-meter b{color:var(--bright);font-weight:400}
@media(max-width:360px){.pipeline-grid,.outreach-actions.two{grid-template-columns:1fr}}
</style>
"""

PIPELINE_SCRIPT = r"""
<script>
function copyHunterMessage(){
  const el=document.getElementById('outreach-message');
  if(!el)return;
  navigator.clipboard.writeText(el.innerText).then(()=>{
    const b=[...document.querySelectorAll('button')].find(x=>x.innerText==='COPY MESSAGE');
    if(b){b.innerText='COPIED ✓';setTimeout(()=>b.innerText='COPY MESSAGE',1200);}
  });
}
function openHunterInstagram(button){
  const nativeUrl=button.dataset.native;
  const webUrl=button.dataset.web;
  let hidden=false;
  const mark=()=>{hidden=true;};
  document.addEventListener('visibilitychange',()=>{if(document.hidden)mark();},{once:true});
  window.addEventListener('pagehide',mark,{once:true});
  window.location.assign(nativeUrl);
  setTimeout(()=>{if(!hidden&&document.visibilityState==='visible')window.location.assign(webUrl);},850);
}
</script>
"""


def _render_action(stage: str, target: dict | None) -> str:
    if not target:
        return "<section class='outreach-card success'><div class='big'>[✓]</div><h1>PIPELINE CLEAR</h1><p class='dim'>No founder action is waiting right now.</p></section>"

    account_id = str(target.get("account_id") or "")
    username_raw = str(target.get("username") or "").strip().lstrip("@")
    username = hunter.esc(username_raw)
    name = hunter.esc(target.get("name") or "")
    context = " // ".join(hunter.esc(x) for x in (target.get("market"), target.get("activity_source")) if x)
    native_url, web_url = _instagram_urls(username_raw)
    open_button = f"<button type='button' class='outreach-open' data-native='{hunter.esc(native_url)}' data-web='{hunter.esc(web_url)}' onclick='openHunterInstagram(this)'>OPEN INSTAGRAM</button>"
    identity = f"<div class='dim'>{name}</div>" if name and name.lower() != username.lower() else ""

    if stage == "ENGAGE":
        content = open_button + "<p class='pipeline-note'>LIKE OR REACT TO SOMETHING REAL. DO NOT FAKE ENGAGEMENT.</p>" + _action_form(account_id, "ENGAGED", "ENGAGED ✓")
        title = "ENGAGE"
    elif stage == "DM_READY":
        content = _copy_block(OPENING_DM, "OPENER") + open_button + _action_form(account_id, "DM_SENT", "DM SENT ✓")
        title = "SEND DM"
    elif stage == "WAITING_REPLY":
        content = open_button + "<div class='outreach-actions two'>" + _action_form(account_id, "HAS_PROBLEM", "HAS PROBLEM") + _action_form(account_id, "INTERESTED", "INTERESTED") + _action_form(account_id, "NO_PROBLEM", "NO PROBLEM", "quiet") + _action_form(account_id, "NOT_INTERESTED", "NOT INTERESTED", "quiet") + "</div>"
        title = "CHECK REPLY"
    elif stage == "PAIN":
        content = _copy_block(PAIN_DM, "FOLLOW-UP") + open_button + "<div class='outreach-actions two'>" + _action_form(account_id, "INTERESTED", "INTERESTED") + _action_form(account_id, "NOT_INTERESTED", "NOT INTERESTED", "quiet") + "</div>"
        title = "PAIN CONFIRMED"
    elif stage == "INTERESTED":
        content = _copy_block(TRIAL_DM, "TRIAL MESSAGE") + open_button + _action_form(account_id, "TRIAL_SENT", "TRIAL SENT ✓")
        title = "SEND TRIAL"
    elif stage == "TRIAL_SENT":
        content = open_button + "<div class='outreach-actions two'>" + _action_form(account_id, "ACTIVATED", "ACTIVATED ✓") + _action_form(account_id, "CLOSE", "CLOSE", "quiet") + "</div>"
        title = "TRIAL FOLLOW-UP"
    else:
        content = ""
        title = stage

    return f"""
      <section class='outreach-card'>
        <div class='outreach-stage'>&gt;&gt; {hunter.esc(title)}</div>
        {identity}
        <h1>@{username}</h1>
        <div class='outreach-context'>{context or 'FOLLOWED TATTOO ARTIST'}</div>
        {content}
      </section>
    """


# Replace the existing Hunter GET with the pipeline. The original swipe discovery screen
# remains available at /owner/hunter/discover.
for route in list(core.app.router.routes):
    if getattr(route, "path", None) == "/owner/hunter" and "GET" in (getattr(route, "methods", set()) or set()):
        core.app.router.routes.remove(route)


@core.app.get("/owner/hunter/discover", response_class=HTMLResponse)
def hunter_discover(request: Request):
    hunter.admin_artist(request)
    return discovery_ui.operator_console_crt(request)


@core.app.post("/owner/hunter/outreach/{account_id}")
async def outreach_action(request: Request, account_id: str):
    hunter.admin_artist(request)
    form = await request.form()
    try:
        _set_stage(account_id, str(form.get("action") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/owner/hunter", status_code=303)


@core.app.get("/owner/hunter", response_class=HTMLResponse)
def hunter_pipeline(request: Request):
    hunter.admin_artist(request)
    db = core.DB()
    try:
        ensure_outreach(db)
        counts = _counts(db)
        dm_today = _dm_today(db)
        pending_new = int(db.execute("SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='PENDING'").fetchone()["n"])
        stage, target = _next_action(db)
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
      {_render_action(stage, target)}
      <p class='pipeline-note'>HUNTER STAGES THE WORK. YOU CONTROL EVERY INSTAGRAM ENGAGEMENT AND DM.</p>
    """
    return core.page("Hunter Pipeline", body, script=PIPELINE_SCRIPT, head=PIPELINE_CSS)


print("Hunter outreach pipeline loaded // manual founder sales workflow", flush=True)
