"""Persistent relationship memory for M4.

Raw conversational evidence is stored separately from later interpretation so M4
can preserve provenance. This module is provider-independent.
"""
import uuid

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
