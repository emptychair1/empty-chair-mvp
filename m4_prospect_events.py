"""Durable event flight recorder for M4 prospect meetings.

The transcript tells us what survived. This log tells us where time and state went:
client lifecycle, raw transcription events, turn assembly, generation, playback,
interruptions, socket/reconnect, and persistence.
"""
import json
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

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
                # Duplicate seq is expected after keepalive retries; event log is idempotent.
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
