"""Private M4 Meeting v2 diagnostic export to the signed-in owner's email.

Restores the prior automatic-analysis path without exposing transcript data publicly.
"""
import html
import json
import threading

from fastapi import Request
from fastapi.responses import JSONResponse

import app as core
import notifications
import meeting_v2 as meeting

_TIMERS = {}
_TIMER_LOCK = threading.Lock()


def _ensure_export_table(conn):
    meeting._ensure_tables(conn)
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


def _owner_email(user):
    conn = core.connect()
    try:
        row = core.db_fetchone(
            conn,
            "SELECT email FROM users WHERE id=? AND shop_id=? LIMIT 1",
            (user["id"], user["shop_id"]),
        )
        return core.normalize_email(row["email"]) if row else None
    finally:
        conn.close()


def _mask_email(value):
    email = core.normalize_email(value)
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = (local[:1] or "*") + "*"
    else:
        masked_local = local[:2] + ("*" * max(2, len(local) - 2))
    return f"{masked_local}@{domain}"


def _session_payload(user, session_id):
    conn = core.connect()
    try:
        _ensure_export_table(conn)
        session = core.db_fetchone(
            conn,
            "SELECT session_id,state_json,created_at,updated_at FROM meeting_v2_sessions WHERE session_id=? AND user_id=? AND shop_id=? LIMIT 1",
            (session_id, user["id"], user["shop_id"]),
        )
        turns = core.db_fetchall(
            conn,
            "SELECT speaker,text,created_at FROM meeting_v2_turns WHERE session_id=? AND user_id=? AND shop_id=? ORDER BY created_at ASC",
            (session_id, user["id"], user["shop_id"]),
        )
        return {
            "session": dict(session) if session else None,
            "turns": [dict(t) for t in turns],
        }
    finally:
        conn.close()


def export_session(user, session_id):
    sid = (session_id or "").strip()
    if not sid:
        return False, "missing session id"

    conn = core.connect()
    try:
        _ensure_export_table(conn)
        existing = core.db_fetchone(
            conn,
            "SELECT status,exported_at FROM m4_analysis_exports WHERE session_id=? AND user_id=? AND shop_id=?",
            (sid, user["id"], user["shop_id"]),
        )
        session = core.db_fetchone(
            conn,
            "SELECT updated_at FROM meeting_v2_sessions WHERE session_id=? AND user_id=? AND shop_id=? LIMIT 1",
            (sid, user["id"], user["shop_id"]),
        )
        if (
            existing
            and existing["status"] == "sent"
            and session
            and str(existing["exported_at"] or "") >= str(session["updated_at"] or "")
        ):
            return True, "already current"
    finally:
        conn.close()

    email = _owner_email(user)
    if not email:
        return False, "owner email unavailable"

    payload = _session_payload(user, sid)
    data = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    body = (
        "<div style='font-family:Arial,sans-serif;max-width:900px;margin:auto'>"
        "<h2>M4 Meeting diagnostic export</h2>"
        f"<p>Session <code>{html.escape(sid)}</code>. Private owner development artifact.</p>"
        f"<pre style='white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f1;padding:16px'>{html.escape(data)}</pre>"
        "</div>"
    )

    ok = False
    error = None
    try:
        ok = bool(notifications.send_email(email, f"M4 DIAGNOSTIC · {sid}", body))
        if not ok:
            error = "email sender returned false"
    except Exception as exc:
        error = str(exc)

    conn = core.connect()
    try:
        _ensure_export_table(conn)
        row = core.db_fetchone(conn, "SELECT session_id FROM m4_analysis_exports WHERE session_id=?", (sid,))
        if row:
            core.db_execute(
                conn,
                "UPDATE m4_analysis_exports SET exported_at=?,status=?,last_error=? WHERE session_id=?",
                (core.now_iso(), "sent" if ok else "failed", error, sid),
            )
        else:
            core.db_execute(
                conn,
                "INSERT INTO m4_analysis_exports(session_id,user_id,shop_id,exported_at,status,last_error) VALUES (?,?,?,?,?,?)",
                (sid, user["id"], user["shop_id"], core.now_iso(), "sent" if ok else "failed", error),
            )
        conn.commit()
    finally:
        conn.close()
    return ok, error


def export_latest_two(user):
    conn = core.connect()
    try:
        meeting._ensure_tables(conn)
        rows = core.db_fetchall(
            conn,
            "SELECT session_id FROM meeting_v2_sessions WHERE user_id=? AND shop_id=? ORDER BY updated_at DESC LIMIT 2",
            (user["id"], user["shop_id"]),
        )
    finally:
        conn.close()
    return [export_session(user, row["session_id"]) for row in rows]


def schedule_latest_two(user, delay_seconds=45):
    """Debounce private export until Meeting activity has gone quiet."""
    key = f"{user['shop_id']}:{user['id']}"
    snapshot = {"id": user["id"], "shop_id": user["shop_id"]}

    def run():
        try:
            export_latest_two(snapshot)
        except Exception as exc:
            print(f"M4 delayed diagnostic export failed: {exc}", flush=True)
        finally:
            with _TIMER_LOCK:
                _TIMERS.pop(key, None)

    with _TIMER_LOCK:
        prior = _TIMERS.get(key)
        if prior:
            prior.cancel()
        timer = threading.Timer(max(5, int(delay_seconds)), run)
        timer.daemon = True
        _TIMERS[key] = timer
        timer.start()


@core.app.get("/api/m4/export-latest-two")
def export_latest_two_now(request: Request):
    """Signed-in owner trigger for exporting only their two latest Meeting v2 sessions."""
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    try:
        results = export_latest_two(user)
        return JSONResponse(
            {"ok": True, "count": len(results), "results": results},
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500, headers={"Cache-Control": "no-store"})


@core.app.get("/api/m4/export-debug")
def export_debug(request: Request):
    """Private delivery diagnostics without transcript content or secrets."""
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)

    email = _owner_email(user)
    conn = core.connect()
    try:
        _ensure_export_table(conn)
        rows = core.db_fetchall(
            conn,
            "SELECT session_id,exported_at,status,last_error FROM m4_analysis_exports WHERE user_id=? AND shop_id=? ORDER BY exported_at DESC LIMIT 2",
            (user["id"], user["shop_id"]),
        )
    finally:
        conn.close()

    return JSONResponse(
        {
            "ok": True,
            "destination": _mask_email(email),
            "email_live": bool(notifications.EMAIL_LIVE),
            "resend_configured": bool(core.RESEND_API_KEY),
            "email_from": core.EMAIL_FROM,
            "latest_exports": [dict(row) for row in rows],
        },
        headers={"Cache-Control": "no-store"},
    )


@core.app.post("/api/m4/prospect-session/finish")
async def finish_and_export(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    try:
        data = await request.json()
        ok, detail = export_session(user, str(data.get("session_id") or ""))
        return JSONResponse({"ok": bool(ok), "detail": detail}, status_code=200 if ok else 500, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500, headers={"Cache-Control": "no-store"})
