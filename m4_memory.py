"""Persistent relationship memory for M4.

Raw conversational evidence is stored separately from later interpretation so M4
can preserve provenance. This module is provider-independent.
"""
import base64
import json
import uuid

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core


def _ensure_table(conn):
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS m4_relationship_turns (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            speaker TEXT NOT NULL,
            text TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'live_audio_transcription',
            created_at TEXT NOT NULL,
            FOREIGN KEY(shop_id) REFERENCES shops(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """,
    )
    core.db_execute(
        conn,
        """
        CREATE INDEX IF NOT EXISTS idx_m4_relationship_turns_user_time
        ON m4_relationship_turns(user_id, created_at)
        """,
    )


def store_turn(user, session_id, speaker, text, source="live_audio_transcription"):
    text = (text or "").strip()
    if not text or speaker not in {"owner", "m4"}:
        return False
    conn = core.connect()
    try:
        _ensure_table(conn)
        core.db_execute(
            conn,
            """
            INSERT INTO m4_relationship_turns(
                id, shop_id, user_id, session_id, speaker, text, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                user["shop_id"],
                user["id"],
                session_id or str(uuid.uuid4()),
                speaker,
                text,
                source,
                core.now_iso(),
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def load_recent(user, limit=40):
    conn = core.connect()
    try:
        _ensure_table(conn)
        rows = core.db_fetchall(
            conn,
            """
            SELECT speaker, text, source, created_at
            FROM m4_relationship_turns
            WHERE user_id = ? AND shop_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user["id"], user["shop_id"], int(limit)),
        )
        conn.commit()
    finally:
        conn.close()
    turns = [dict(row) for row in rows]
    turns.reverse()
    return turns


def load_transcript(user, limit=200):
    """Return recent relationship evidence with session provenance for private review."""
    limit = max(1, min(int(limit), 500))
    conn = core.connect()
    try:
        _ensure_table(conn)
        rows = core.db_fetchall(
            conn,
            """
            SELECT session_id, speaker, text, source, created_at
            FROM m4_relationship_turns
            WHERE user_id = ? AND shop_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user["id"], user["shop_id"], limit),
        )
        conn.commit()
    finally:
        conn.close()
    turns = [dict(row) for row in rows]
    turns.reverse()
    return turns


def _group_transcript(turns):
    sessions = []
    by_id = {}
    for turn in turns:
        sid = turn.get("session_id") or "unknown"
        if sid not in by_id:
            session = {"session_id": sid, "turns": []}
            by_id[sid] = session
            sessions.append(session)
        by_id[sid]["turns"].append({
            "speaker": turn.get("speaker"),
            "text": turn.get("text"),
            "source": turn.get("source"),
            "created_at": turn.get("created_at"),
        })
    return sessions


@core.app.get("/m4-transcript-export", response_class=HTMLResponse)
def transcript_export_page(request: Request):
    user = core.get_current_user(request)
    if not user:
        return core.login_required_redirect(request)[1]
    return HTMLResponse(
        """<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>M4 transcript export</title>
        <style>body{font-family:system-ui,sans-serif;background:#f3f3ef;color:#1b1d19;display:grid;place-items:center;min-height:100vh;margin:0}.box{max-width:520px;padding:28px;text-align:center}h1{font:500 28px Georgia,serif}p{line-height:1.5;color:#666}.btn{border:1px solid #bbb;border-radius:999px;background:transparent;padding:13px 20px;font:500 17px Georgia,serif;cursor:pointer;color:#222}</style></head>
        <body><div class=\"box\"><h1>Send M4 transcript to yourself</h1><p>This emails only your recent M4 relationship transcript to the email address on your Empty Chair account. It does not expose the transcript publicly.</p><form method=\"post\" action=\"/api/m4/email-transcript\"><button class=\"btn\" type=\"submit\">Email my transcript</button></form></div></body></html>"""
    )


@core.app.post("/api/m4/email-transcript")
def email_transcript(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    if not core.RESEND_API_KEY:
        return JSONResponse({"error": "Email delivery is not configured."}, status_code=503)

    turns = load_transcript(user, limit=500)
    sessions = _group_transcript(turns)
    payload = {
        "exported_at": core.now_iso(),
        "owner_name": user["name"],
        "turn_count": len(turns),
        "sessions": sessions,
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    attachment = base64.b64encode(raw).decode("ascii")

    try:
        core.resend.api_key = core.RESEND_API_KEY
        result = core.resend.Emails.send({
            "from": core.EMAIL_FROM,
            "to": [user["email"]],
            "subject": "M4 relationship transcript export",
            "text": "Attached is your private M4 relationship transcript export for analysis.",
            "attachments": [{
                "content": attachment,
                "filename": "m4-relationship-transcript.json",
            }],
        })
        return HTMLResponse(
            "<!doctype html><html><body style='font-family:system-ui;background:#f3f3ef;color:#1b1d19;display:grid;place-items:center;min-height:100vh'><div style='text-align:center'><h2>Sent.</h2><p>Your M4 transcript was emailed to your account address.</p><a href='/m4-lab'>Back to M4</a></div></body></html>",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return JSONResponse({"error": f"Transcript email failed: {exc}"}, status_code=502)
