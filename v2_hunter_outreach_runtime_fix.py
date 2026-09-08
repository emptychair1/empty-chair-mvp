"""Hunter runtime routes: Watchtower intelligence, fresh discovery, and outreach."""
import os
from html import escape
from urllib.parse import quote
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import v2_app as core
import v2_hunter_operator as hunter
import v2_hunter_outreach as outreach

_bridge=os.getenv("HUNTER_WATCHTOWER_BRIDGE_TOKEN","").strip()
if _bridge: os.environ["WATCHTOWER_API_TOKEN"]=_bridge
import v2_hunter_crt_ui as lead_ui

TABLE="hunter_outreach_v2"
CREATE_TABLE=f"""CREATE TABLE IF NOT EXISTS {TABLE} (account_id TEXT PRIMARY KEY,stage TEXT NOT NULL DEFAULT 'ENGAGE',outcome TEXT,followed_at TEXT,engaged_at TEXT,dm_sent_at TEXT,replied_at TEXT,trial_sent_at TEXT,activated_at TEXT,updated_at TEXT NOT NULL)"""
STAGES=("ENGAGE","DM_READY","WAITING_REPLY","PAIN","INTERESTED","TRIAL_SENT","ACTIVATED","CLOSED"); ACTIONS=outreach.ACTIONS
NAV_CSS="""<style>.hunter-section-nav{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin:0 0 22px}.hunter-section-nav a{border:1px solid var(--off);padding:10px 5px;text-align:center;text-decoration:none;color:var(--dim);font-size:9px;letter-spacing:.05em;white-space:nowrap}.hunter-section-nav a.active{border-color:var(--amber);color:var(--bright)}.fresh-list{display:grid;gap:10px}.fresh-card{border:1px solid var(--off);border-radius:14px;padding:15px;background:rgba(11,9,5,.94);display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center}.fresh-user{font-size:17px;color:var(--bright);overflow-wrap:anywhere}.fresh-meta{font-size:9px;color:var(--dim);margin-top:5px;text-transform:uppercase}.fresh-card a{text-decoration:none;white-space:nowrap}.fresh-empty{border:1px solid var(--off);border-radius:14px;padding:28px 16px;text-align:center;color:var(--dim)}</style>"""

def ensure_runtime_outreach(db):
    hunter.ensure_tables(db); db.execute(CREATE_TABLE); db.commit()
    existing={str(dict(r).get("account_id") or "") for r in db.execute(f"SELECT account_id FROM {TABLE}").fetchall()}; stamp=hunter.now(); changed=False
    for row in db.execute("SELECT account_id,decided_at,last_ingested_at FROM hunter_operator_targets WHERE decision='HANDLED' AND account_id IS NOT NULL").fetchall():
        item=dict(row); aid=str(item.get("account_id") or "")
        if aid and aid not in existing: db.execute(f"INSERT INTO {TABLE}(account_id,stage,followed_at,updated_at) VALUES(?,?,?,?)",(aid,"ENGAGE",item.get("decided_at") or item.get("last_ingested_at") or stamp,stamp)); existing.add(aid); changed=True
    if changed: db.commit()

def counts(db):
    result={s:0 for s in STAGES}
    for row in db.execute(f"SELECT stage,COUNT(*) AS n FROM {TABLE} GROUP BY stage").fetchall():
        x=dict(row); s=str(x.get("stage") or ""); result[s]=int(x.get("n") or 0) if s in result else result.get(s,0)
    return result

def dm_today(db):
    row=db.execute(f"SELECT COUNT(*) AS n FROM {TABLE} WHERE dm_sent_at LIKE ?",(hunter._today_prefix()+"%",)).fetchone(); return int(dict(row).get("n") or 0) if row else 0

def target_for_stage(db,stage):
    row=db.execute(f"SELECT o.*,t.username,t.profile_url,t.snapshot_json,t.score FROM {TABLE} o JOIN hunter_operator_targets t ON t.account_id=o.account_id WHERE o.stage=? ORDER BY o.updated_at ASC,t.score DESC,t.username ASC LIMIT 1",(stage,)).fetchone()
    if not row:return None
    item=dict(row); snap=hunter.load_json(item.get("snapshot_json"),{})
    if isinstance(snap,dict): item["name"]=snap.get("name"); item["market"]=snap.get("market"); item["activity_source"]=snap.get("activity_source")
    return item

def next_action(db):
    for stage in ("INTERESTED","PAIN","DM_READY","ENGAGE","WAITING_REPLY","TRIAL_SENT"):
        target=target_for_stage(db,stage)
        if target:return stage,target
    return "DONE",None

def set_stage(account_id,action):
    action=str(action or "").upper()
    if action not in ACTIONS:raise ValueError("invalid outreach action")
    db=core.DB()
    try:
        ensure_runtime_outreach(db); row=db.execute(f"SELECT * FROM {TABLE} WHERE account_id=?",(account_id,)).fetchone()
        if not row:raise ValueError("outreach artist not found")
        current=dict(row); stamp=hunter.now(); u={"updated_at":stamp}
        if action=="ENGAGED":u.update(stage="DM_READY",engaged_at=stamp)
        elif action=="DM_SENT":u.update(stage="WAITING_REPLY",dm_sent_at=stamp)
        elif action=="HAS_PROBLEM":u.update(stage="PAIN",outcome="HAS_PROBLEM",replied_at=stamp)
        elif action=="INTERESTED":u.update(stage="INTERESTED",outcome="INTERESTED",replied_at=current.get("replied_at") or stamp)
        elif action=="NO_PROBLEM":u.update(stage="CLOSED",outcome="NO_PROBLEM",replied_at=stamp)
        elif action=="NOT_INTERESTED":u.update(stage="CLOSED",outcome="NOT_INTERESTED",replied_at=current.get("replied_at") or stamp)
        elif action=="TRIAL_SENT":u.update(stage="TRIAL_SENT",trial_sent_at=stamp)
        elif action=="ACTIVATED":u.update(stage="ACTIVATED",activated_at=stamp)
        elif action=="CLOSE":u.update(stage="CLOSED",outcome=current.get("outcome") or "CLOSED")
        db.execute(f"UPDATE {TABLE} SET "+",".join(f"{k}=?" for k in u)+" WHERE account_id=?",tuple(u.values())+(account_id,)); db.commit()
    finally: db.close()

def nav(active,count=None):
    n=f" ({count:,})" if count is not None else ""
    return NAV_CSS+f"<div class='hunter-section-nav'><a class='{'active' if active=='watchtower' else ''}' href='/owner/hunter/watchtower'>WATCHTOWER</a><a class='{'active' if active=='new' else ''}' href='/owner/hunter/new-artists'>NEW ARTISTS{n}</a><a class='{'active' if active=='outreach' else ''}' href='/owner/hunter/outreach'>OUTREACH</a></div>"

def decorate(response,active,count=None):
    doc=response.body.decode("utf-8"); marker="</header>"; block=nav(active,count); doc=doc.replace(marker,marker+block,1) if marker in doc else block+doc
    return HTMLResponse(doc,status_code=response.status_code,headers={"Cache-Control":"no-store"})

for route in list(core.app.router.routes):
    path=getattr(route,"path",None); methods=getattr(route,"methods",set()) or set()
    if path in {"/owner/hunter","/owner/hunter/watchtower","/owner/hunter/outreach","/owner/hunter/discover","/owner/hunter/discovery","/owner/hunter/new","/owner/hunter/new-artists"} and "GET" in methods: core.app.router.routes.remove(route)
    elif path=="/owner/hunter/outreach/{account_id}" and "POST" in methods: core.app.router.routes.remove(route)

@core.app.get("/owner/hunter",response_class=HTMLResponse)
@core.app.get("/owner/hunter/watchtower",response_class=HTMLResponse)
def watchtower_page(request:Request): return decorate(lead_ui.hunter_command_center(request),"watchtower")

@core.app.get("/owner/hunter/discover")
@core.app.get("/owner/hunter/discovery")
@core.app.get("/owner/hunter/new")
def discovery_redirect(request:Request): hunter.admin_artist(request); return RedirectResponse("/owner/hunter/new-artists",status_code=303)

@core.app.get("/owner/hunter/new-artists",response_class=HTMLResponse)
def new_artists_page(request:Request):
    hunter.admin_artist(request); error=None; targets=[]
    try:
        payload=lead_ui._watchtower("/v1/targets",timeout=15); targets=[x for x in (payload.get("targets") or []) if isinstance(x,dict)]; targets.sort(key=lambda x:(str(x.get("created_at") or ""),int(x.get("priority") or 0)),reverse=True)
    except Exception as exc:error=str(exc)
    cards=[]
    for item in targets[:200]:
        username=str(item.get("username") or "").strip().lstrip("@"); source=str(item.get("source") or "unknown").replace("discovery:web:","web // ").replace("_"," ").upper(); priority=int(item.get("priority") or 0); url=f"https://www.instagram.com/{quote(username,safe='._')}/"
        cards.append(f"<div class='fresh-card'><div><div class='fresh-user'>@{escape(username)}</div><div class='fresh-meta'>{escape(source)} // PRIORITY {priority}</div></div><a class='button secondary' href='{escape(url)}' target='_blank' rel='noopener'>OPEN ↗</a></div>")
    content=f"<div class='fresh-empty'>WATCHTOWER UNAVAILABLE<br><small>{escape(error)}</small></div>" if error else "<div class='fresh-list'>"+"".join(cards)+"</div>" if cards else "<div class='fresh-empty'>NO DISCOVERED ARTISTS YET</div>"
    body=nav("new",len(targets))+f"<p class='dim' style='margin:0 0 5px'>HUNTER // DISCOVERY</p><h1 style='margin-top:0'>NEW ARTISTS</h1><p class='dim'>LIVE WATCHTOWER TARGET ROSTER</p>{content}"
    return core.page("Hunter New Artists",body,head=outreach.PIPELINE_CSS)

@core.app.post("/owner/hunter/outreach/{account_id}")
async def outreach_action(request:Request,account_id:str):
    hunter.admin_artist(request); form=await request.form(); set_stage(account_id,str(form.get("action") or "")); return RedirectResponse("/owner/hunter/outreach",status_code=303)

@core.app.get("/owner/hunter/outreach",response_class=HTMLResponse)
def outreach_page(request:Request):
    hunter.admin_artist(request); db=core.DB()
    try: ensure_runtime_outreach(db); c=counts(db); sent=dm_today(db); stage,target=next_action(db)
    finally: db.close()
    body=nav("outreach")+f"<p class='dim' style='margin:0 0 5px'>FOUNDER // ACQUISITION</p><h1 style='margin-top:0'>HUNTER OUTREACH</h1><div class='pipeline-grid'><div class='pipe-stat'><b>{c.get('ENGAGE',0):,}</b><span>TO ENGAGE</span></div><div class='pipe-stat'><b>{c.get('DM_READY',0):,}</b><span>TO DM</span></div><div class='pipe-stat'><b>{c.get('WAITING_REPLY',0):,}</b><span>WAITING REPLY</span></div><div class='pipe-stat'><b>{c.get('PAIN',0)+c.get('INTERESTED',0):,}</b><span>LIVE OPPORTUNITIES</span></div><div class='pipe-stat'><b>{c.get('TRIAL_SENT',0):,}</b><span>TRIAL SENT</span></div><div class='pipe-stat'><b>{c.get('ACTIVATED',0):,}</b><span>ACTIVATED</span></div></div><div class='dm-meter'>DM SENT TODAY // <b>{sent:,}</b> &nbsp; TARGET // 20–30</div>{outreach._render_action(stage,target)}"
    return core.page("Hunter Outreach",body,script=outreach.PIPELINE_SCRIPT,head=outreach.PIPELINE_CSS)

print("Hunter runtime loaded // Watchtower is source of truth",flush=True)
