"""Email finished M4 prospect diagnostics to the signed-in owner.

This keeps private meeting data inside the owner's account/email flow while allowing
the connected development assistant to retrieve the latest diagnostic email later.
"""
import html
import json

from fastapi import Request
from fastapi.responses import JSONResponse

import app as core
import notifications
import m4_prospect_transcript as transcript
import m4_prospect_events as events
import m4_prospect_checkpoint as checkpoints


def _ensure_export_table(conn):
    transcript._ensure_table(conn)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS m4_analysis_exports (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            shop_id TEXT NOT NULL,
            exported_at TEXT NOT NULL,
            status TEXT NOT NULL,
            last_error TEXT
        )
    """)


def _owner_email(user_id, shop_id):
    conn = core.connect()
    try:
        row = core.db_fetchone(conn, "SELECT email FROM users WHERE id=? AND shop_id=? LIMIT 1", (user_id, shop_id))
        return core.normalize_email(row['email']) if row else None
    finally:
        conn.close()


def _payload(user, session_id):
    return {
        'session_id': session_id,
        'transcript': transcript.session_turns(user, session_id, 1000),
        'checkpoint': checkpoints.get_checkpoint(user, session_id),
        'events': events.session_events(user, session_id, 5000),
        'analysis_contract': {
            'definition_of_done': 'transcript plus event-trace analysis',
            'failure_classes': [
                'LOCAL_NETWORK','GEMINI_UPSTREAM','EMPTY_CHAIR_TRANSPORT',
                'TRANSCRIPTION_ASSEMBLY','M4_BEHAVIOR','PERSISTENCE','UNKNOWN'
            ],
        },
    }


def export_session(user, session_id):
    sid = (session_id or '').strip()
    if not sid:
        return False, 'missing session id'
    conn = core.connect()
    try:
        _ensure_export_table(conn)
        existing = core.db_fetchone(conn, "SELECT status FROM m4_analysis_exports WHERE session_id=? AND user_id=? AND shop_id=?", (sid, user['id'], user['shop_id']))
        if existing and existing['status'] == 'sent':
            return True, 'already sent'
    finally:
        conn.close()

    email = _owner_email(user['id'], user['shop_id'])
    if not email:
        return False, 'owner email unavailable'

    payload = _payload(user, sid)
    data = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    body = (
        "<div style='font-family:Arial,sans-serif;max-width:900px;margin:auto'>"
        "<h2>M4 meeting diagnostic export</h2>"
        f"<p>Session <code>{html.escape(sid)}</code>. Private development artifact; separate from M4 relationship memory.</p>"
        "<p>This message contains the canonical transcript, any surviving checkpoint, and the event flight recorder.</p>"
        f"<pre style='white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f1;padding:16px'>{html.escape(data)}</pre>"
        "</div>"
    )
    ok = False
    error = None
    try:
        ok = bool(notifications.send_email(email, f"M4 DIAGNOSTIC · {sid}", body))
        if not ok:
            error = 'email sender returned false'
    except Exception as exc:
        error = str(exc)

    conn = core.connect()
    try:
        _ensure_export_table(conn)
        row = core.db_fetchone(conn, "SELECT session_id FROM m4_analysis_exports WHERE session_id=?", (sid,))
        if row:
            core.db_execute(conn, "UPDATE m4_analysis_exports SET exported_at=?,status=?,last_error=? WHERE session_id=?", (core.now_iso(), 'sent' if ok else 'failed', error, sid))
        else:
            core.db_execute(conn, "INSERT INTO m4_analysis_exports(session_id,user_id,shop_id,exported_at,status,last_error) VALUES (?,?,?,?,?,?)", (sid, user['id'], user['shop_id'], core.now_iso(), 'sent' if ok else 'failed', error))
        conn.commit()
    finally:
        conn.close()
    return ok, error


@core.app.post('/api/m4/prospect-session/export-analysis')
async def export_analysis(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({'error':'Sign in first.'}, status_code=401)
    try:
        data = await request.json()
        ok, detail = export_session(user, str(data.get('session_id') or ''))
        return JSONResponse({'ok':bool(ok),'detail':detail}, status_code=200 if ok else 500, headers={'Cache-Control':'no-store'})
    except Exception as exc:
        return JSONResponse({'error':str(exc)}, status_code=500, headers={'Cache-Control':'no-store'})


def _install_finish_hook():
    """Attach export to the already-registered authenticated finish route."""
    for route in core.app.routes:
        if getattr(route, 'path', None) != '/api/m4/prospect-session/finish':
            continue
        if 'POST' not in (getattr(route, 'methods', set()) or set()):
            continue
        dependant = getattr(route, 'dependant', None)
        original = getattr(dependant, 'call', None)
        if not original or getattr(original, '_m4_analysis_wrapped', False):
            return

        async def wrapped(request: Request, _original=original):
            result = await _original(request)
            try:
                user = core.get_current_user(request)
                data = await request.json()
                sid = str(data.get('session_id') or '')
                if user and sid:
                    export_session(user, sid)
            except Exception as exc:
                print('M4 diagnostic export failed:', str(exc))
            return result

        wrapped._m4_analysis_wrapped = True
        dependant.call = wrapped
        route.endpoint = wrapped
        return


_install_finish_hook()
