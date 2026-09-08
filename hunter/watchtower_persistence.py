"""Durable persistence primitives for Hunter Watchtower.

This module is intentionally inert unless WATCHTOWER_DATABASE_URL is configured.
It never falls back to the Empty Chair application's DATABASE_URL, so enabling
Hunter persistence cannot accidentally mutate the production application schema.

Browser storage state is encrypted before it leaves the Watchtower process.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from cryptography.fernet import Fernet, InvalidToken
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("WATCHTOWER_DATABASE_URL", "").strip()
SESSION_KEY = os.getenv("WATCHTOWER_SESSION_KEY", "").strip()
SCHEMA = "hunter_watchtower"
SESSION_NAME = "instagram_storage_state"


def enabled() -> bool:
    return bool(DATABASE_URL)


def session_enabled() -> bool:
    return enabled() and bool(SESSION_KEY)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fernet() -> Fernet:
    if not SESSION_KEY:
        raise RuntimeError("WATCHTOWER_SESSION_KEY is not configured")
    try:
        return Fernet(SESSION_KEY.encode("ascii"))
    except Exception as exc:
        raise RuntimeError("WATCHTOWER_SESSION_KEY must be a valid Fernet key") from exc


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    if not DATABASE_URL:
        raise RuntimeError("WATCHTOWER_DATABASE_URL is not configured")
    with psycopg.connect(DATABASE_URL, autocommit=False, row_factory=dict_row) as conn:
        yield conn
        conn.commit()


def init() -> None:
    if not enabled():
        return
    with connection() as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA}.watchtower_jobs (
                id TEXT PRIMARY KEY,
                collector TEXT NOT NULL,
                username TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                result_json JSONB,
                error TEXT
            )
            """
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_watchtower_jobs_status_created ON {SCHEMA}.watchtower_jobs(status, created_at)"
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA}.secure_state (
                name TEXT PRIMARY KEY,
                ciphertext BYTEA NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA}.pain_ledger (
                id BIGSERIAL PRIMARY KEY,
                username TEXT NOT NULL,
                collector TEXT NOT NULL,
                signal_status TEXT NOT NULL,
                intent_score INTEGER NOT NULL DEFAULT 0,
                matches JSONB NOT NULL DEFAULT '[]'::jsonb,
                observed_at TIMESTAMPTZ NOT NULL,
                job_id TEXT UNIQUE REFERENCES {SCHEMA}.watchtower_jobs(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_pain_ledger_username_observed ON {SCHEMA}.pain_ledger(username, observed_at DESC)"
        )
        # A crashed/restarted single worker may leave a job marked running.
        conn.execute(
            f"UPDATE {SCHEMA}.watchtower_jobs SET status='queued', started_at=NULL WHERE status='running'"
        )


def save_session_state(state: dict[str, Any]) -> None:
    if not session_enabled():
        raise RuntimeError("durable encrypted session persistence is not configured")
    plaintext = json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ciphertext = _fernet().encrypt(plaintext)
    with connection() as conn:
        conn.execute(
            f"""
            INSERT INTO {SCHEMA}.secure_state(name, ciphertext, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (name) DO UPDATE SET ciphertext=EXCLUDED.ciphertext, updated_at=NOW()
            """,
            (SESSION_NAME, ciphertext),
        )


def load_session_state() -> dict[str, Any] | None:
    if not session_enabled():
        return None
    with connection() as conn:
        row = conn.execute(
            f"SELECT ciphertext FROM {SCHEMA}.secure_state WHERE name=%s",
            (SESSION_NAME,),
        ).fetchone()
    if not row:
        return None
    try:
        plaintext = _fernet().decrypt(bytes(row["ciphertext"]))
        payload = json.loads(plaintext.decode("utf-8"))
    except (InvalidToken, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("stored Watchtower session could not be decrypted") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("stored Watchtower session has invalid shape")
    return payload


def enqueue_job(job_id: str, collector: str, username: str, created_at: str) -> None:
    with connection() as conn:
        conn.execute(
            f"INSERT INTO {SCHEMA}.watchtower_jobs(id, collector, username, status, created_at) VALUES (%s,%s,%s,'queued',%s)",
            (job_id, collector, username, created_at),
        )


def next_job() -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            f"""
            SELECT * FROM {SCHEMA}.watchtower_jobs
            WHERE status='queued'
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ).fetchone()
        if row:
            conn.execute(
                f"UPDATE {SCHEMA}.watchtower_jobs SET status='running', started_at=NOW() WHERE id=%s",
                (row["id"],),
            )
    return dict(row) if row else None


def finish_job(job_id: str, result: dict[str, Any]) -> None:
    with connection() as conn:
        conn.execute(
            f"UPDATE {SCHEMA}.watchtower_jobs SET status='finished', finished_at=NOW(), result_json=%s::jsonb, error=NULL WHERE id=%s",
            (json.dumps(result, ensure_ascii=False), job_id),
        )
        conn.execute(
            f"""
            INSERT INTO {SCHEMA}.pain_ledger(username, collector, signal_status, intent_score, matches, observed_at, job_id)
            VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s)
            ON CONFLICT (job_id) DO NOTHING
            """,
            (
                result.get("username", ""),
                result.get("collector", "instagram_story"),
                result.get("status", "unknown"),
                int(result.get("intent_score") or 0),
                json.dumps(result.get("matches") or [], ensure_ascii=False),
                result.get("observed_at") or utcnow(),
                job_id,
            ),
        )


def fail_job(job_id: str, error: str) -> None:
    with connection() as conn:
        conn.execute(
            f"UPDATE {SCHEMA}.watchtower_jobs SET status='failed', finished_at=NOW(), error=%s WHERE id=%s",
            (error[:2000], job_id),
        )


def get_job(job_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(f"SELECT * FROM {SCHEMA}.watchtower_jobs WHERE id=%s", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM {SCHEMA}.watchtower_jobs ORDER BY created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def job_counts() -> dict[str, int]:
    with connection() as conn:
        rows = conn.execute(
            f"SELECT status, COUNT(*) AS count FROM {SCHEMA}.watchtower_jobs GROUP BY status"
        ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}
