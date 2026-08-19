"""Private prospect Meeting transcript capture.

This store is intentionally separate from M4 relationship memory. It exists for QA,
conversation analysis, latency measurement, and sales-experience review.
"""
import json
import uuid

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core


def _ensure_table(conn):
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS m4_prospect_turns (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            speaker TEXT NOT NULL,
            text TEXT NOT NULL,
            latency_ms INTEGER,
            source TEXT NOT NULL DEFAULT 'gemini_live_transcription',
            created_at TEXT NOT NULL,
            FOREIGN KEY(shop_id) REFERENCES shops(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """,
    )
    core.db_execute(
        conn,
        """
        CREATE INDEX IF NOT EXISTS idx_m4_prospect_turns_user_time
        ON m4_prospect_turns(user_id, created_at)
        """,
    )


def store_turn(user, session_id, speaker, text, latency_ms=None):
    text = (text or "").strip()
    if not text or speaker not in {"prospect", "m4"}:
        return False
    latency = None
    if latency_ms is not None:
        try:
            latency = max(0, min(int(latency_ms), 120000))
        except Exception:
            latency = None
    conn = core.connect()
    try:
        _ensure_table(conn)
        core.db_execute(
            conn,
            """
            INSERT INTO m4_prospect_turns(
                id, shop_id, user_id, session_id, speaker, text, latency_ms, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()), user["shop_id"], user["id"],
                session_id or str(uuid.uuid4()), speaker, text, latency,
                "gemini_live_transcription", core.now_iso(),
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def load_turns(user, limit=500, session_id=None):
    limit = max(1, min(int(limit), 2000))
    conn = core.connect()
    try:
        _ensure_table(conn)
        if session_id:
            rows = core.db_fetchall(
                conn,
                """
                SELECT session_id, speaker, text, latency_ms, source, created_at
                FROM m4_prospect_turns
                WHERE user_id = ? AND shop_id = ? AND session_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (user["id"], user["shop_id"], session_id, limit),
            )
        else:
            rows = core.db_fetchall(
                conn,
                """
                SELECT session_id, speaker, text, latency_ms, source, created_at
                FROM m4_prospect_turns
                WHERE user_id = ? AND shop_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user["id"], user["shop_id"], limit),
            )
        conn.commit()
    finally:
        conn.close()
    turns = [dict(r) for r in rows]
    if not session_id:
        turns.reverse()
    return turns


@core.app.post("/api/m4/prospect-turn")
async def prospect_turn(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    try:
        data = await request.json()
        ok = store_turn(
            user,
            str(data.get("session_id") or ""),
            str(data.get("speaker") or ""),
            str(data.get("text") or ""),
            data.get("latency_ms"),
        )
        return {"ok": bool(ok)}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@core.app.get("/api/m4/prospect-transcript")
def prospect_transcript(request: Request, limit: int = 500, session_id: str = ""):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    turns = load_turns(user, limit=limit, session_id=(session_id or None))
    sessions = {}
    for t in turns:
        sessions.setdefault(t["session_id"], []).append(t)
    payload = {
        "count": len(turns),
        "sessions": [
            {"session_id": sid, "turns": ts}
            for sid, ts in sessions.items()
        ],
    }
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@core.app.get("/m4-prospect-transcripts", response_class=HTMLResponse)
def prospect_transcripts_page(request: Request):
    user = core.get_current_user(request)
    if not user:
        return core.login_required_redirect(request)[1]
    turns = load_turns(user, limit=1000)
    sessions = {}
    for t in turns:
        sessions.setdefault(t["session_id"], []).append(t)
    blocks = []
    for sid, ts in reversed(list(sessions.items())):
        rows = []
        for t in ts:
            who = "M4" if t["speaker"] == "m4" else "Prospect"
            latency = "" if t.get("latency_ms") is None else f" · {t['latency_ms']} ms"
            text = (t.get("text") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            rows.append(f"<div class='turn'><div class='meta'>{who}{latency} · {t['created_at']}</div><div class='text'>{text}</div></div>")
        blocks.append(f"<section><h2>{sid}</h2>{''.join(rows)}</section>")
    body = "".join(blocks) or "<p>No prospect transcript captured yet.</p>"
    return HTMLResponse(
        """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>M4 Prospect Transcripts</title><style>
        body{font-family:system-ui,sans-serif;background:#f3f3ef;color:#1b1d19;max-width:900px;margin:0 auto;padding:28px}h1{font:500 30px Georgia,serif}h2{font:500 15px ui-monospace,monospace;color:#70756b;margin-top:34px}.turn{padding:14px 0;border-top:1px solid #d9dbd3}.meta{font:11px ui-monospace,monospace;color:#858a80;margin-bottom:6px}.text{font:16px/1.45 Georgia,serif;white-space:pre-wrap}.note{color:#777;font-size:13px;line-height:1.5}</style></head><body><h1>Prospect Meeting transcripts</h1><p class='note'>Private QA record. Separate from M4 relationship memory. Latency is measured from detected end-of-prospect speech to first returned M4 audio when available.</p>"""
        + body
        + "</body></html>",
        headers={"Cache-Control": "no-store"},
    )
