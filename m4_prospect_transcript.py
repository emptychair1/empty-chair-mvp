"""Private, reconnectable prospect transcript capture for M4 meetings."""
import uuid
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
import app as core


def _ensure_table(conn):
    core.db_execute(conn,"""CREATE TABLE IF NOT EXISTS m4_prospect_turns (id TEXT PRIMARY KEY,shop_id TEXT NOT NULL,user_id TEXT NOT NULL,session_id TEXT NOT NULL,speaker TEXT NOT NULL,text TEXT NOT NULL,source TEXT NOT NULL DEFAULT 'gemini_live_prospect',latency_ms INTEGER,created_at TEXT NOT NULL,FOREIGN KEY(shop_id) REFERENCES shops(id),FOREIGN KEY(user_id) REFERENCES users(id))""")
    core.db_execute(conn,"CREATE INDEX IF NOT EXISTS idx_m4_prospect_turns_user_time ON m4_prospect_turns(user_id, created_at)")
    core.db_execute(conn,"CREATE INDEX IF NOT EXISTS idx_m4_prospect_turns_session_time ON m4_prospect_turns(user_id, shop_id, session_id, created_at)")


def store_turn(user,session_id,speaker,text,latency_ms=None):
    text=(text or '').strip()
    if not text or speaker not in {'prospect','m4'}:return False
    conn=core.connect()
    try:
        _ensure_table(conn)
        core.db_execute(conn,"""INSERT INTO m4_prospect_turns(id,shop_id,user_id,session_id,speaker,text,source,latency_ms,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",(str(uuid.uuid4()),user['shop_id'],user['id'],session_id or str(uuid.uuid4()),speaker,text,'gemini_live_prospect',int(latency_ms) if latency_ms is not None else None,core.now_iso()))
        conn.commit();return True
    finally:conn.close()


def session_turns(user,session_id,limit=200):
    if not session_id:return []
    conn=core.connect()
    try:
        _ensure_table(conn)
        rows=core.db_fetchall(conn,"""SELECT speaker,text,source,latency_ms,created_at FROM m4_prospect_turns WHERE user_id=? AND shop_id=? AND session_id=? ORDER BY created_at ASC LIMIT ?""",(user['id'],user['shop_id'],session_id,int(limit)))
        conn.commit();return [dict(r) for r in rows]
    finally:conn.close()


def latest_session(user):
    conn=core.connect()
    try:
        _ensure_table(conn)
        # Pick the session whose activity was updated most recently. Grouping prevents
        # an arbitrary individual row from defining what 'latest meeting' means.
        row=core.db_fetchone(conn,"""SELECT session_id, MAX(created_at) AS last_activity, MIN(created_at) AS started_at, COUNT(*) AS turn_count FROM m4_prospect_turns WHERE user_id=? AND shop_id=? GROUP BY session_id ORDER BY last_activity DESC, started_at DESC LIMIT 1""",(user['id'],user['shop_id']))
        if not row:return None,[]
        sid=row['session_id'];return sid,session_turns(user,sid,500)
    finally:conn.close()


def _requested_session(request,user):
    sid=(request.query_params.get('session') or '').strip()
    if sid:
        turns=session_turns(user,sid,500)
        if turns:return sid,turns
    return latest_session(user)


@core.app.post('/api/m4/prospect-turn')
async def prospect_turn(request:Request):
    user=core.get_current_user(request)
    if not user:return JSONResponse({'error':'Sign in first.'},status_code=401)
    try:
        d=await request.json();ok=store_turn(user,str(d.get('session_id') or ''),str(d.get('speaker') or ''),str(d.get('text') or ''),d.get('latency_ms'));return JSONResponse({'ok':bool(ok)},headers={'Cache-Control':'no-store'})
    except Exception as exc:return JSONResponse({'error':str(exc)},status_code=400)


@core.app.get('/api/m4/prospect-session/{session_id}')
def prospect_session(request:Request,session_id:str):
    user=core.get_current_user(request)
    if not user:return JSONResponse({'error':'Sign in first.'},status_code=401)
    turns=session_turns(user,session_id,80);compact=[{'speaker':t['speaker'],'text':t['text']} for t in turns[-40:]]
    return JSONResponse({'session_id':session_id,'turns':compact},headers={'Cache-Control':'no-store'})


@core.app.get('/api/m4/prospect-transcript/latest')
def prospect_transcript_latest(request:Request):
    user=core.get_current_user(request)
    if not user:return JSONResponse({'error':'Sign in first.'},status_code=401)
    sid,turns=_requested_session(request,user);return JSONResponse({'session_id':sid,'count':len(turns),'turns':turns},headers={'Cache-Control':'no-store'})


@core.app.get('/m4-prospect-transcript',response_class=HTMLResponse)
def prospect_transcript_page(request:Request):
    user=core.get_current_user(request)
    if not user:return core.login_required_redirect(request)[1]
    sid,turns=_requested_session(request,user);rows=[]
    for t in turns:
        latency=f" · {t['latency_ms']} ms response" if t.get('speaker')=='m4' and t.get('latency_ms') is not None else ''
        speaker='M4' if t.get('speaker')=='m4' else 'Prospect';text=str(t.get('text') or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
        rows.append(f"<article><div class='meta'>{speaker}{latency} · {t.get('created_at','')}</div><div class='text'>{text}</div></article>")
    body=''.join(rows) or "<p class='empty'>No prospect transcript has been captured yet.</p>"
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>M4 Prospect Transcript</title><style>body{{margin:0;background:#f3f3ef;color:#1b1d19;font-family:system-ui,sans-serif}}main{{max-width:760px;margin:0 auto;padding:28px 18px 60px}}h1{{font:500 30px Georgia,serif;margin:0 0 6px}}.sid,.meta{{font:11px ui-monospace,monospace;color:#7b8076}}.sid{{margin-bottom:28px}}article{{padding:18px 0;border-top:1px solid #d8dad2}}.text{{font:17px/1.55 Georgia,serif;margin-top:7px}}</style></head><body><main><h1>Latest M4 prospect transcript</h1><div class='sid'>session: {sid or 'none'} · private · separate from relationship memory</div>{body}</main></body></html>""",headers={'Cache-Control':'no-store, no-cache, must-revalidate','Pragma':'no-cache','Expires':'0'})
