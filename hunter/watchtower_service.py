"""Hunter Watchtower: authenticated cloud Story observer and control API."""
from __future__ import annotations
import json,os,re,sqlite3,threading,time,uuid
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from fastapi import Depends,FastAPI,Header,HTTPException
from pydantic import BaseModel,Field
from playwright.sync_api import BrowserContext,Page,sync_playwright
from hunter.story_watch import classify_recovery
from hunter import watchtower_persistence as durable
SCHEMA="empty-chair-hunter-watchtower-v1";DATA_DIR=Path(os.getenv("WATCHTOWER_DATA_DIR","/data"));DB_PATH=Path(os.getenv("WATCHTOWER_DB_PATH",str(DATA_DIR/"watchtower.sqlite3")));PROFILE_DIR=Path(os.getenv("WATCHTOWER_PROFILE_DIR",str(DATA_DIR/"chromium-profile")));API_TOKEN=os.getenv("WATCHTOWER_API_TOKEN","").strip();HEADLESS=os.getenv("WATCHTOWER_HEADLESS","true").lower() not in {"0","false","no"};POLL_SECONDS=max(1.,float(os.getenv("WATCHTOWER_POLL_SECONDS","3")));SETTLE_SECONDS=max(1.,float(os.getenv("WATCHTOWER_SETTLE_SECONDS","4")));SCHEDULER_SECONDS=max(15.,float(os.getenv("WATCHTOWER_SCHEDULER_SECONDS","30")))
app=FastAPI(title="Hunter Watchtower",version="1.3.0");_stop=threading.Event();_worker=None;_scheduler=None
_worker_state={"started_at":None,"last_heartbeat":None,"last_job_id":None,"browser_started":False,"authenticated":False,"last_error":None,"durable_jobs":durable.enabled(),"durable_session":durable.session_enabled(),"durable_session_restored":False,"scheduler_started":False,"last_schedule_at":None,"last_scheduled_count":0}
class JobRequest(BaseModel):username:str=Field(min_length=1,max_length=64);collector:str=Field(default="instagram_story")
class BatchRequest(BaseModel):usernames:list[str]=Field(min_length=1,max_length=500);collector:str=Field(default="instagram_story")
class TargetRequest(BaseModel):username:str=Field(min_length=1,max_length=64);interval_minutes:int=Field(default=60,ge=15,le=1440);priority:int=Field(default=50,ge=0,le=100);source:str=Field(default="manual",max_length=64);enabled:bool=True
def utcnow():return datetime.now(timezone.utc).isoformat()
def clean_username(value):
    clean=value.strip().lower().lstrip("@")
    if not re.fullmatch(r"[a-z0-9._]{1,64}",clean):raise ValueError("invalid Instagram username")
    return clean
@contextmanager
def db():
    DATA_DIR.mkdir(parents=True,exist_ok=True);conn=sqlite3.connect(DB_PATH,timeout=30);conn.row_factory=sqlite3.Row
    try:yield conn;conn.commit()
    finally:conn.close()
def init_db():
    DATA_DIR.mkdir(parents=True,exist_ok=True);PROFILE_DIR.mkdir(parents=True,exist_ok=True)
    if durable.enabled():durable.init();return
    with db() as c:c.executescript("CREATE TABLE IF NOT EXISTS watchtower_jobs(id TEXT PRIMARY KEY,collector TEXT NOT NULL,username TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,result_json TEXT,error TEXT);CREATE INDEX IF NOT EXISTS idx_watchtower_jobs_status_created ON watchtower_jobs(status,created_at);")
def require_token(authorization:str|None=Header(default=None)):
    if not API_TOKEN:raise HTTPException(status_code=503,detail="WATCHTOWER_API_TOKEN is not configured")
    if authorization!=f"Bearer {API_TOKEN}":raise HTTPException(status_code=401,detail="unauthorized")
def enqueue(username,collector):
    if collector!="instagram_story":raise HTTPException(status_code=400,detail="unsupported collector")
    try:clean=clean_username(username)
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc
    jid,created=str(uuid.uuid4()),utcnow()
    if durable.enabled():durable.enqueue_job(jid,collector,clean,created)
    else:
        with db() as c:c.execute("INSERT INTO watchtower_jobs(id,collector,username,status,created_at) VALUES(?,?,?,'queued',?)",(jid,collector,clean,created))
    return {"id":jid,"collector":collector,"username":clean,"status":"queued","created_at":created}
def next_job():
    if durable.enabled():return durable.next_job()
    with db() as c:
        row=c.execute("SELECT * FROM watchtower_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if row:c.execute("UPDATE watchtower_jobs SET status='running',started_at=? WHERE id=? AND status='queued'",(utcnow(),row['id']))
        return row
def finish_job(jid,result):
    if durable.enabled():durable.finish_job(jid,result);return
    with db() as c:c.execute("UPDATE watchtower_jobs SET status='finished',finished_at=?,result_json=?,error=NULL WHERE id=?",(utcnow(),json.dumps(result),jid))
def fail_job(jid,error):
    if durable.enabled():durable.fail_job(jid,error);return
    with db() as c:c.execute("UPDATE watchtower_jobs SET status='failed',finished_at=?,error=? WHERE id=?",(utcnow(),error[:2000],jid))
def visible_text(page):
    try:return page.locator("body").inner_text(timeout=5000).strip()
    except Exception:return ""
def authenticated(page,context):
    if "/accounts/login" in page.url.lower() or "/auth_platform/" in page.url.lower():return False
    try:return any(c.get("name")=="sessionid" for c in context.cookies("https://www.instagram.com"))
    except Exception:return False
def maybe_open_story_confirmation(page):
    text=visible_text(page).lower()
    if "view story" not in text or "will be able to see that you viewed their story" not in text:return False
    try:
        loc=page.get_by_text("View story",exact=True)
        if loc.count()>0:loc.first.click(timeout=5000);page.wait_for_timeout(int(SETTLE_SECONDS*1000));return True
    except Exception:return False
    return False
def persist_browser_state(context):
    if durable.session_enabled():
        try:durable.save_session_state(context.storage_state())
        except Exception as exc:_worker_state['last_error']=f"session persistence: {exc.__class__.__name__}: {exc}"
def restore_browser_state(context):
    if not durable.session_enabled():return False
    try:
        state=durable.load_session_state();cookies=(state or {}).get('cookies') or []
        if cookies:context.add_cookies(cookies)
        _worker_state['durable_session_restored']=bool(cookies);return bool(cookies)
    except Exception as exc:_worker_state['last_error']=f"session restore: {exc.__class__.__name__}: {exc}";return False
def probe_story(page,context,username):
    page.goto(f"https://www.instagram.com/stories/{username}/",wait_until="domcontentloaded",timeout=45000);page.wait_for_timeout(int(SETTLE_SECONDS*1000));auth=authenticated(page,context);_worker_state['authenticated']=auth
    if not auth:return {"schema":SCHEMA,"username":username,"collector":"instagram_story","status":"unknown_auth_failure","intent_score":0,"matches":[],"observed_at":utcnow()}
    clicked=maybe_open_story_confirmation(page);persist_browser_state(context);text,current=visible_text(page),page.url
    if f"/stories/{username}/" not in current.lower():return {"schema":SCHEMA,"username":username,"collector":"instagram_story","status":"unknown_no_viewable_story","intent_score":0,"matches":[],"interstitial_clicked":clicked,"observed_at":utcnow()}
    classification=classify_recovery(text);return {"schema":SCHEMA,"username":username,"collector":"instagram_story","status":"recovery_story_found" if classification['recovery'] else "story_visible_no_recovery_text","intent_score":classification['intent_score'],"matches":classification['matches'],"interstitial_clicked":clicked,"visible_text":text[:4000],"observed_at":utcnow()}
def scheduler_loop():
    _worker_state['scheduler_started']=True
    while not _stop.is_set():
        try:
            jobs=durable.enqueue_due_targets(25) if durable.enabled() else [];_worker_state['last_schedule_at']=utcnow();_worker_state['last_scheduled_count']=len(jobs)
        except Exception as exc:_worker_state['last_error']=f"scheduler: {exc.__class__.__name__}: {exc}"
        _stop.wait(SCHEDULER_SECONDS)
def worker_loop():
    _worker_state['started_at']=utcnow()
    while not _stop.is_set():
        try:
            with sync_playwright() as p:
                context=p.chromium.launch_persistent_context(user_data_dir=str(PROFILE_DIR),headless=HEADLESS,viewport={"width":1280,"height":900},args=["--no-sandbox","--disable-dev-shm-usage"]);_worker_state['browser_started']=True;restore_browser_state(context);page=context.pages[0] if context.pages else context.new_page()
                try:page.goto("https://www.instagram.com/",wait_until="domcontentloaded",timeout=45000);page.wait_for_timeout(1500);_worker_state['authenticated']=authenticated(page,context);persist_browser_state(context) if _worker_state['authenticated'] else None
                except Exception as exc:_worker_state['last_error']=f"startup auth check: {exc.__class__.__name__}: {exc}"
                while not _stop.is_set():
                    _worker_state['last_heartbeat']=utcnow();row=next_job()
                    if not row:time.sleep(POLL_SECONDS);continue
                    _worker_state['last_job_id']=row['id']
                    try:finish_job(row['id'],probe_story(page,context,row['username']));_worker_state['last_error']=None
                    except Exception as exc:message=f"{exc.__class__.__name__}: {exc}";fail_job(row['id'],message);_worker_state['last_error']=message
                context.close()
        except Exception as exc:_worker_state['browser_started']=False;_worker_state['authenticated']=False;_worker_state['last_error']=f"browser loop: {exc.__class__.__name__}: {exc}";time.sleep(5)
def row_payload(row):
    payload=dict(row);value=payload.pop('result_json',None);payload['result']=json.loads(value) if isinstance(value,str) and value else value
    for k,v in list(payload.items()):
        if isinstance(v,datetime):payload[k]=v.isoformat()
    return payload
@app.on_event("startup")
def on_startup():
    global _worker,_scheduler
    init_db();_worker=threading.Thread(target=worker_loop,name="hunter-watchtower",daemon=True);_worker.start();_scheduler=threading.Thread(target=scheduler_loop,name="hunter-scheduler",daemon=True);_scheduler.start()
@app.on_event("shutdown")
def on_shutdown():_stop.set()
@app.get("/healthz")
def healthz():return {"ok":True,"schema":SCHEMA,"browser_started":_worker_state['browser_started'],"authenticated":_worker_state['authenticated'],"last_heartbeat":_worker_state['last_heartbeat'],"durable_jobs":durable.enabled(),"durable_session":durable.session_enabled(),"durable_session_restored":_worker_state['durable_session_restored'],"scheduler_started":_worker_state['scheduler_started'],"last_schedule_at":_worker_state['last_schedule_at']}
@app.get("/v1/status",dependencies=[Depends(require_token)])
def status():return {"schema":SCHEMA,"worker":dict(_worker_state),"jobs":durable.job_counts() if durable.enabled() else {}}
@app.post("/v1/jobs",dependencies=[Depends(require_token)])
def create_job(request:JobRequest):return enqueue(request.username,request.collector)
@app.post("/v1/jobs/batch",dependencies=[Depends(require_token)])
def create_batch(request:BatchRequest):
    jobs=[enqueue(u,request.collector) for u in request.usernames];return {"count":len(jobs),"jobs":jobs}
@app.get("/v1/jobs/{job_id}",dependencies=[Depends(require_token)])
def get_job(job_id:str):
    row=durable.get_job(job_id) if durable.enabled() else None
    if not row:raise HTTPException(status_code=404,detail="job not found")
    return row_payload(row)
@app.get("/v1/jobs",dependencies=[Depends(require_token)])
def list_jobs(limit:int=50):
    rows=durable.list_jobs(max(1,min(limit,200))) if durable.enabled() else [];return {"count":len(rows),"jobs":[row_payload(r) for r in rows]}
@app.post("/v1/targets",dependencies=[Depends(require_token)])
def put_target(request:TargetRequest):
    if not durable.enabled():raise HTTPException(status_code=503,detail="durable persistence required")
    try:username=clean_username(request.username)
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc
    return durable.upsert_target(username,request.interval_minutes,request.priority,request.source,request.enabled)
@app.get("/v1/targets",dependencies=[Depends(require_token)])
def targets():return {"targets":durable.list_targets() if durable.enabled() else []}
@app.get("/v1/leads",dependencies=[Depends(require_token)])
def leads(limit:int=100):return {"leads":durable.lead_rankings(max(1,min(limit,500))) if durable.enabled() else []}
