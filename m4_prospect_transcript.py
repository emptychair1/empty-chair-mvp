"""Private, reconnectable prospect transcript capture for M4 meetings."""
import html
import uuid
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
import app as core


def _ensure_table(conn):
    core.db_execute(conn,"""CREATE TABLE IF NOT EXISTS m4_prospect_turns (id TEXT PRIMARY KEY,shop_id TEXT NOT NULL,user_id TEXT NOT NULL,session_id TEXT NOT NULL,speaker TEXT NOT NULL,text TEXT NOT NULL,source TEXT NOT NULL DEFAULT 'gemini_live_prospect',latency_ms INTEGER,created_at TEXT NOT NULL,FOREIGN KEY(shop_id) REFERENCES shops(id),FOREIGN KEY(user_id) REFERENCES users(id))""")
    core.db_execute(conn,"CREATE INDEX IF NOT EXISTS idx_m4_prospect_turns_user_time ON m4_prospect_turns(user_id, created_at)")
    core.db_execute(conn,"CREATE INDEX IF NOT EXISTS idx_m4_prospect_turns_session_time ON m4_prospect_turns(user_id, shop_id, session_id, created_at)")
    core.db_execute(conn,"""CREATE TABLE IF NOT EXISTS m4_prospect_sessions (session_id TEXT PRIMARY KEY,shop_id TEXT NOT NULL,user_id TEXT NOT NULL,started_at TEXT NOT NULL,last_activity TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'recording',turn_count INTEGER NOT NULL DEFAULT 0,last_error TEXT,FOREIGN KEY(shop_id) REFERENCES shops(id),FOREIGN KEY(user_id) REFERENCES users(id))""")
    core.db_execute(conn,"CREATE INDEX IF NOT EXISTS idx_m4_prospect_sessions_activity ON m4_prospect_sessions(user_id,shop_id,last_activity)")


def start_session(user,session_id):
    sid=(session_id or '').strip() or str(uuid.uuid4());now=core.now_iso();conn=core.connect()
    try:
        _ensure_table(conn)
        row=core.db_fetchone(conn,"SELECT session_id FROM m4_prospect_sessions WHERE session_id=? AND user_id=? AND shop_id=?",(sid,user['id'],user['shop_id']))
        if row: core.db_execute(conn,"UPDATE m4_prospect_sessions SET status='recording',last_activity=?,last_error=NULL WHERE session_id=?",(now,sid))
        else: core.db_execute(conn,"INSERT INTO m4_prospect_sessions(session_id,shop_id,user_id,started_at,last_activity,status,turn_count) VALUES (?,?,?,?,?,'recording',0)",(sid,user['shop_id'],user['id'],now,now))
        conn.commit();return sid
    finally:conn.close()


def mark_session(user,session_id,status,last_error=None):
    conn=core.connect()
    try:
        _ensure_table(conn);core.db_execute(conn,"UPDATE m4_prospect_sessions SET status=?,last_activity=?,last_error=? WHERE session_id=? AND user_id=? AND shop_id=?",(status,core.now_iso(),last_error,session_id,user['id'],user['shop_id']));conn.commit()
    finally:conn.close()


def store_turn(user,session_id,speaker,text,latency_ms=None):
    text=(text or '').strip();sid=(session_id or '').strip()
    if not text or speaker not in {'prospect','m4'} or not sid:return False
    conn=core.connect()
    try:
        _ensure_table(conn);now=core.now_iso()
        core.db_execute(conn,"""INSERT INTO m4_prospect_turns(id,shop_id,user_id,session_id,speaker,text,source,latency_ms,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",(str(uuid.uuid4()),user['shop_id'],user['id'],sid,speaker,text,'gemini_live_prospect',int(latency_ms) if latency_ms is not None else None,now))
        core.db_execute(conn,"UPDATE m4_prospect_sessions SET last_activity=?,turn_count=turn_count+1,status='recording',last_error=NULL WHERE session_id=? AND user_id=? AND shop_id=?",(now,sid,user['id'],user['shop_id']))
        conn.commit();return True
    finally:conn.close()


def session_turns(user,session_id,limit=500):
    if not session_id:return []
    conn=core.connect()
    try:
        _ensure_table(conn);rows=core.db_fetchall(conn,"SELECT speaker,text,source,latency_ms,created_at FROM m4_prospect_turns WHERE user_id=? AND shop_id=? AND session_id=? ORDER BY created_at ASC LIMIT ?",(user['id'],user['shop_id'],session_id,int(limit)));conn.commit();return [dict(r) for r in rows]
    finally:conn.close()


def list_sessions(user,limit=50):
    """Return every recoverable session, including sessions captured before the session-health table existed."""
    conn=core.connect()
    try:
        _ensure_table(conn)
        turn_groups=core.db_fetchall(conn,"""SELECT session_id, MIN(created_at) AS started_at, MAX(created_at) AS last_activity, COUNT(*) AS turn_count FROM m4_prospect_turns WHERE user_id=? AND shop_id=? GROUP BY session_id ORDER BY last_activity DESC""",(user['id'],user['shop_id']))
        health_rows=core.db_fetchall(conn,"""SELECT session_id,started_at,last_activity,status,turn_count,last_error FROM m4_prospect_sessions WHERE user_id=? AND shop_id=? ORDER BY last_activity DESC""",(user['id'],user['shop_id']))
        conn.commit()
    finally:conn.close()
    merged={}
    for r in health_rows:
        d=dict(r);merged[d['session_id']]={**d,'source':'session_health'}
    for r in turn_groups:
        d=dict(r);sid=d['session_id'];base=merged.get(sid,{})
        # Turn evidence wins for timestamps/count because it proves actual captured content.
        merged[sid]={**base,**d,'status':base.get('status') or 'legacy_captured','last_error':base.get('last_error'),'source':'turn_evidence'}
    rows=list(merged.values());rows.sort(key=lambda x:(x.get('last_activity') or '',x.get('started_at') or ''),reverse=True)
    return rows[:max(1,min(int(limit),200))]


def latest_session(user):
    sessions=list_sessions(user,1)
    if not sessions:return None,[]
    sid=sessions[0]['session_id'];return sid,session_turns(user,sid,500)


def _requested_session(request,user):
    sid=(request.query_params.get('session') or '').strip()
    if sid:
        turns=session_turns(user,sid,500)
        # Return an explicitly requested session even if it has zero turns so health-only sessions are inspectable.
        if turns or any(s['session_id']==sid for s in list_sessions(user,200)):return sid,turns
    return latest_session(user)


@core.app.post('/api/m4/prospect-session/start')
async def prospect_session_start(request:Request):
    user=core.get_current_user(request)
    if not user:return JSONResponse({'error':'Sign in first.'},status_code=401)
    try:
        d=await request.json();sid=start_session(user,str(d.get('session_id') or ''));return JSONResponse({'ok':True,'session_id':sid,'status':'recording','turn_count':len(session_turns(user,sid,500))},headers={'Cache-Control':'no-store'})
    except Exception as exc:return JSONResponse({'error':str(exc)},status_code=500)


@core.app.post('/api/m4/prospect-session/finish')
async def prospect_session_finish(request:Request):
    user=core.get_current_user(request)
    if not user:return JSONResponse({'error':'Sign in first.'},status_code=401)
    d=await request.json();sid=str(d.get('session_id') or '');mark_session(user,sid,'finished');return {'ok':True}


@core.app.get('/api/m4/prospect-session/{session_id}/status')
def prospect_session_status(request:Request,session_id:str):
    user=core.get_current_user(request)
    if not user:return JSONResponse({'error':'Sign in first.'},status_code=401)
    matches=[s for s in list_sessions(user,200) if s['session_id']==session_id]
    return JSONResponse(matches[0] if matches else {'error':'Session not found.'},status_code=200 if matches else 404,headers={'Cache-Control':'no-store'})


@core.app.post('/api/m4/prospect-turn')
async def prospect_turn(request:Request):
    user=core.get_current_user(request)
    if not user:return JSONResponse({'error':'Sign in first.'},status_code=401)
    try:
        d=await request.json();ok=store_turn(user,str(d.get('session_id') or ''),str(d.get('speaker') or ''),str(d.get('text') or ''),d.get('latency_ms'));return JSONResponse({'ok':bool(ok)},headers={'Cache-Control':'no-store'})
    except Exception as exc:return JSONResponse({'error':str(exc)},status_code=500)


@core.app.get('/api/m4/prospect-session/{session_id}')
def prospect_session(request:Request,session_id:str):
    user=core.get_current_user(request)
    if not user:return JSONResponse({'error':'Sign in first.'},status_code=401)
    turns=session_turns(user,session_id,80);return JSONResponse({'session_id':session_id,'turns':[{'speaker':t['speaker'],'text':t['text']} for t in turns[-40:]]},headers={'Cache-Control':'no-store'})


@core.app.get('/api/m4/prospect-transcript/sessions')
def prospect_transcript_sessions(request:Request):
    user=core.get_current_user(request)
    if not user:return JSONResponse({'error':'Sign in first.'},status_code=401)
    return JSONResponse({'sessions':list_sessions(user,100)},headers={'Cache-Control':'no-store, no-cache, must-revalidate'})


@core.app.get('/api/m4/prospect-transcript/latest')
def prospect_transcript_latest(request:Request):
    user=core.get_current_user(request)
    if not user:return JSONResponse({'error':'Sign in first.'},status_code=401)
    sid,turns=_requested_session(request,user);return JSONResponse({'session_id':sid,'count':len(turns),'turns':turns},headers={'Cache-Control':'no-store, no-cache, must-revalidate'})


def _render_turns(turns):
    rows=[]
    for t in turns:
        latency=f" · {t['latency_ms']} ms response" if t.get('speaker')=='m4' and t.get('latency_ms') is not None else ''
        speaker='M4' if t.get('speaker')=='m4' else 'Prospect';text=html.escape(str(t.get('text') or ''))
        rows.append(f"<article><div class='meta'>{speaker}{latency} · {html.escape(str(t.get('created_at','')))}</div><div class='text'>{text}</div></article>")
    return ''.join(rows) or "<p class='empty'>No turns captured for this session.</p>"


@core.app.get('/m4-prospect-transcripts',response_class=HTMLResponse)
def prospect_transcripts_index(request:Request):
    user=core.get_current_user(request)
    if not user:return core.login_required_redirect(request)[1]
    cards=[]
    for s in list_sessions(user,100):
        sid=html.escape(str(s.get('session_id') or ''));started=html.escape(str(s.get('started_at') or ''));last=html.escape(str(s.get('last_activity') or ''));count=int(s.get('turn_count') or 0);status=html.escape(str(s.get('status') or 'unknown'))
        cards.append(f"<a class='card' href='/m4-prospect-transcript?session={sid}'><strong>{sid}</strong><span>{count} turns · {status}</span><span>started {started}</span><span>last activity {last}</span></a>")
    body=''.join(cards) or '<p>No sessions found.</p>'
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>M4 Transcript Recovery</title><style>body{{margin:0;background:#f3f3ef;color:#1b1d19;font-family:system-ui}}main{{max-width:820px;margin:auto;padding:28px 18px 60px}}h1{{font:500 30px Georgia,serif}}p{{color:#6f746b}}.card{{display:flex;flex-direction:column;gap:5px;padding:16px 0;border-top:1px solid #d8dad2;color:#1b1d19;text-decoration:none}}.card strong{{font:13px ui-monospace,monospace}}.card span{{font:11px ui-monospace,monospace;color:#777c73}}</style></head><body><main><h1>All recoverable M4 prospect sessions</h1><p>Includes legacy transcript sessions captured before recording-health tracking existed.</p>{body}</main></body></html>""",headers={'Cache-Control':'no-store, no-cache, must-revalidate','Pragma':'no-cache','Expires':'0'})


@core.app.get('/m4-prospect-transcript',response_class=HTMLResponse)
def prospect_transcript_page(request:Request):
    user=core.get_current_user(request)
    if not user:return core.login_required_redirect(request)[1]
    sid,turns=_requested_session(request,user)
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>M4 Prospect Transcript</title><style>body{{margin:0;background:#f3f3ef;color:#1b1d19;font-family:system-ui}}main{{max-width:760px;margin:auto;padding:28px 18px 60px}}h1{{font:500 30px Georgia,serif}}.sid,.meta{{font:11px ui-monospace,monospace;color:#7b8076}}article{{padding:18px 0;border-top:1px solid #d8dad2}}.text{{font:17px/1.55 Georgia,serif;margin-top:7px}}a{{color:#4d5d17}}</style></head><body><main><h1>M4 prospect transcript</h1><div class='sid'>session: {html.escape(str(sid or 'none'))} · private · separate from relationship memory</div><p><a href='/m4-prospect-transcripts'>View all recoverable sessions</a></p>{_render_turns(turns)}</main></body></html>""",headers={'Cache-Control':'no-store, no-cache, must-revalidate','Pragma':'no-cache','Expires':'0'})
