"""Durable live checkpoints for in-progress M4 prospect turns.

Final transcript rows remain canonical. Checkpoints protect partial input/output text
when a websocket, browser, or playback lifecycle ends before the normal final write.
"""
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

import app as core
import m4_prospect_transcript as transcript


def _ensure_checkpoint_table(conn):
    transcript._ensure_table(conn)
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS m4_prospect_checkpoints (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            input_text TEXT NOT NULL DEFAULT '',
            output_text TEXT NOT NULL DEFAULT '',
            latency_ms INTEGER,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, shop_id, session_id)
        )
        """,
    )


def checkpoint(user, session_id, input_text='', output_text='', latency_ms=None):
    sid = (session_id or '').strip()
    if not sid:
        return False
    conn = core.connect()
    try:
        _ensure_checkpoint_table(conn)
        now = core.now_iso()
        row = core.db_fetchone(
            conn,
            "SELECT id FROM m4_prospect_checkpoints WHERE user_id=? AND shop_id=? AND session_id=?",
            (user['id'], user['shop_id'], sid),
        )
        values = ((input_text or '').strip(), (output_text or '').strip(), int(latency_ms) if latency_ms is not None else None, now)
        if row:
            core.db_execute(
                conn,
                "UPDATE m4_prospect_checkpoints SET input_text=?,output_text=?,latency_ms=?,updated_at=? WHERE id=?",
                values + (row['id'],),
            )
        else:
            core.db_execute(
                conn,
                "INSERT INTO m4_prospect_checkpoints(id,shop_id,user_id,session_id,input_text,output_text,latency_ms,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), user['shop_id'], user['id'], sid) + values,
            )
        core.db_execute(
            conn,
            "UPDATE m4_prospect_sessions SET last_activity=? WHERE session_id=? AND user_id=? AND shop_id=?",
            (now, sid, user['id'], user['shop_id']),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def clear_checkpoint(user, session_id):
    conn = core.connect()
    try:
        _ensure_checkpoint_table(conn)
        core.db_execute(
            conn,
            "DELETE FROM m4_prospect_checkpoints WHERE user_id=? AND shop_id=? AND session_id=?",
            (user['id'], user['shop_id'], session_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_checkpoint(user, session_id):
    conn = core.connect()
    try:
        _ensure_checkpoint_table(conn)
        row = core.db_fetchone(
            conn,
            "SELECT input_text,output_text,latency_ms,updated_at FROM m4_prospect_checkpoints WHERE user_id=? AND shop_id=? AND session_id=?",
            (user['id'], user['shop_id'], session_id),
        )
        return dict(row) if row else None
    finally:
        conn.close()


@core.app.post('/api/m4/prospect-checkpoint')
async def prospect_checkpoint(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({'error': 'Sign in first.'}, status_code=401)
    try:
        data = await request.json()
        ok = checkpoint(
            user,
            str(data.get('session_id') or ''),
            str(data.get('input_text') or ''),
            str(data.get('output_text') or ''),
            data.get('latency_ms'),
        )
        return JSONResponse({'ok': bool(ok)}, headers={'Cache-Control': 'no-store'})
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=500)


@core.app.post('/api/m4/prospect-checkpoint/clear')
async def prospect_checkpoint_clear(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({'error': 'Sign in first.'}, status_code=401)
    data = await request.json()
    clear_checkpoint(user, str(data.get('session_id') or ''))
    return JSONResponse({'ok': True}, headers={'Cache-Control': 'no-store'})


# Make recovery/transcript reads include any surviving in-progress checkpoint.
_original_session_turns = transcript.session_turns


def _session_turns_with_checkpoint(user, session_id, limit=500):
    turns = _original_session_turns(user, session_id, limit)
    draft = get_checkpoint(user, session_id)
    if not draft:
        return turns
    if draft.get('input_text'):
        turns.append({
            'speaker': 'prospect',
            'text': draft['input_text'],
            'source': 'gemini_live_checkpoint',
            'latency_ms': None,
            'created_at': draft.get('updated_at'),
        })
    if draft.get('output_text'):
        turns.append({
            'speaker': 'm4',
            'text': draft['output_text'],
            'source': 'gemini_live_checkpoint',
            'latency_ms': draft.get('latency_ms'),
            'created_at': draft.get('updated_at'),
        })
    return turns


transcript.session_turns = _session_turns_with_checkpoint
