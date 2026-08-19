"""Durable event flight recorder for M4 prospect meetings.

The transcript tells us what survived. This log tells us where time and state went:
client lifecycle, raw transcription events, turn assembly, generation, playback,
interruptions, socket/reconnect, and persistence.
"""
import html
import json
import uuid

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core
import m4_prospect_transcript as transcript

MAX_DETAIL = 12000


def _ensure_table(conn):
    transcript._ensure_table(conn)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS m4_prospect_events (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            generation INTEGER,
            client_ms INTEGER,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(user_id, shop_id, session_id, seq)
        )
    """)


def record_events(user, session_id, events):
    sid = (session_id or '').strip()
    if not sid or not isinstance(events, list):
        return 0
    conn = core.connect()
    try:
        _ensure_table(conn)
        count = 0
        for event in events[:250]:
            if not isinstance(event, dict):
                continue
            try:
                seq = int(event.get('seq'))
            except Exception:
                continue
            event_type = str(event.get('type') or '').strip()[:80]
            if not event_type:
                continue
            generation = event.get('generation')
            client_ms = event.get('client_ms')
            try: generation = int(generation) if generation is not None else None
            except Exception: generation = None
            try: client_ms = int(client_ms) if client_ms is not None else None
            except Exception: client_ms = None
            detail = event.get('detail')
            if not isinstance(detail, str):
                detail = json.dumps(detail, default=str, separators=(',', ':'))
            detail = detail[:MAX_DETAIL]
            try:
                core.db_execute(conn, """
                    INSERT INTO m4_prospect_events
                    (id,shop_id,user_id,session_id,seq,event_type,generation,client_ms,detail,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (str(uuid.uuid4()), user['shop_id'], user['id'], sid, seq,
                      event_type, generation, client_ms, detail, core.now_iso()))
                count += 1
            except Exception:
                pass
        conn.commit()
        return count
    finally:
        conn.close()


def session_events(user, session_id, limit=2000):
    conn = core.connect()
    try:
        _ensure_table(conn)
        rows = core.db_fetchall(conn, """
            SELECT seq,event_type,generation,client_ms,detail,created_at
            FROM m4_prospect_events
            WHERE user_id=? AND shop_id=? AND session_id=?
            ORDER BY seq ASC LIMIT ?
        """, (user['id'], user['shop_id'], session_id, max(1, min(int(limit), 5000))))
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _session_for_request(request, user):
    sid = (request.query_params.get('session') or '').strip()
    if sid:
        return sid
    sid, _ = transcript.latest_session(user)
    return sid


@core.app.post('/api/m4/prospect-events')
async def prospect_events(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({'error':'Sign in first.'}, status_code=401)
    try:
        data = await request.json()
        count = record_events(user, str(data.get('session_id') or ''), data.get('events') or [])
        return JSONResponse({'ok':True,'stored':count}, headers={'Cache-Control':'no-store'})
    except Exception as exc:
        return JSONResponse({'error':str(exc)}, status_code=500)


@core.app.get('/api/m4/prospect-events/{session_id}')
def prospect_events_get(request: Request, session_id: str, limit: int=2000):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({'error':'Sign in first.'}, status_code=401)
    return JSONResponse({'session_id':session_id,'events':session_events(user, session_id, limit)},
                        headers={'Cache-Control':'no-store'})


@core.app.get('/m4-prospect-diagnostics', response_class=HTMLResponse)
def prospect_diagnostics(request: Request):
    user = core.get_current_user(request)
    if not user:
        return core.login_required_redirect(request)[1]
    sid = _session_for_request(request, user)
    if not sid:
        return HTMLResponse('<h1>No M4 prospect session found.</h1>', headers={'Cache-Control':'no-store'})
    turns = transcript.session_turns(user, sid, 500)
    events = session_events(user, sid, 5000)
    turn_html = []
    for t in turns:
        who = 'M4' if t.get('speaker') == 'm4' else 'Prospect'
        latency = f" · {t.get('latency_ms')} ms" if t.get('latency_ms') is not None else ''
        turn_html.append(f"<article><div class='meta'>{html.escape(who)}{latency} · {html.escape(str(t.get('created_at') or ''))}</div><div class='text'>{html.escape(str(t.get('text') or ''))}</div></article>")
    event_html = []
    for e in events:
        event_html.append(
            "<tr>"
            f"<td>{e.get('seq')}</td><td>{e.get('client_ms')}</td><td>{e.get('generation')}</td>"
            f"<td>{html.escape(str(e.get('event_type') or ''))}</td>"
            f"<td><pre>{html.escape(str(e.get('detail') or ''))}</pre></td>"
            "</tr>"
        )
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>M4 Meeting Diagnostics</title><style>
body{{margin:0;background:#f3f3ef;color:#1b1d19;font-family:system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:28px 18px 60px}}h1,h2{{font-family:Georgia,serif;font-weight:500}}.sid,.meta{{font:11px ui-monospace,monospace;color:#74786f}}article{{padding:14px 0;border-top:1px solid #d8dad2}}.text{{font:16px/1.5 Georgia,serif;margin-top:6px}}table{{width:100%;border-collapse:collapse;font:11px ui-monospace,monospace}}th,td{{border-top:1px solid #d8dad2;padding:7px;vertical-align:top;text-align:left}}pre{{margin:0;white-space:pre-wrap;word-break:break-word;font:inherit}}
</style></head><body><main><h1>M4 Meeting Diagnostics</h1><div class='sid'>session: {html.escape(sid)} · private</div><h2>Transcript</h2>{''.join(turn_html) or '<p>No transcript turns.</p>'}<h2>Event flight recorder</h2><table><thead><tr><th>#</th><th>client ms</th><th>gen</th><th>event</th><th>detail</th></tr></thead><tbody>{''.join(event_html)}</tbody></table></main></body></html>""", headers={'Cache-Control':'no-store, no-cache, must-revalidate','Pragma':'no-cache','Expires':'0'})
