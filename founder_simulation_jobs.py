"""Background job runner for long Crybaby founder simulation runs.

Long simulations must not keep an HTTP request open. The route creates a job,
returns immediately, and this worker advances the simulation one optimized
cycle at a time while persisting progress in PostgreSQL/SQLite.
"""

from __future__ import annotations

import uuid

import app as core
import m4_founder_simulation_engine_v2 as engine
from founder_simulation_safety import load_and_assert_founder_simulation_target


def ensure_table(conn):
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS founder_sim_jobs (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            requested_cycles INTEGER NOT NULL,
            completed_cycles INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            error TEXT,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        )
        """,
    )


def _job_row(conn, job_id, shop_id):
    return core.db_fetchone(
        conn,
        "SELECT * FROM founder_sim_jobs WHERE id=? AND shop_id=? LIMIT 1",
        (job_id, shop_id),
    )


def create_job(shop_id, requested_cycles):
    requested_cycles = max(1, min(int(requested_cycles), 365))
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_table(conn)
        running = core.db_fetchone(
            conn,
            "SELECT id FROM founder_sim_jobs WHERE shop_id=? AND status='RUNNING' ORDER BY started_at DESC LIMIT 1",
            (shop_id,),
        )
        if running:
            conn.rollback()
            return str(running["id"]), False

        job_id = "founder_sim_job_" + uuid.uuid4().hex
        now = core.now_iso()
        core.db_execute(
            conn,
            """INSERT INTO founder_sim_jobs(
                id,shop_id,requested_cycles,completed_cycles,status,error,
                started_at,updated_at,finished_at
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (job_id, shop_id, requested_cycles, 0, "RUNNING", None, now, now, None),
        )
        conn.commit()
        return job_id, True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_job(job_id, shop_id):
    """Execute one persisted job. Intended for FastAPI BackgroundTasks."""
    conn = core.connect()
    try:
        ensure_table(conn)
        row = _job_row(conn, job_id, shop_id)
        if not row or row["status"] != "RUNNING":
            conn.rollback()
            return
        requested = int(row["requested_cycles"])
        completed = int(row["completed_cycles"] or 0)
        conn.rollback()
    finally:
        conn.close()

    try:
        while completed < requested:
            engine.run_simulation(shop_id, cycles=1)
            completed += 1
            progress_conn = core.connect()
            try:
                core.db_execute(
                    progress_conn,
                    "UPDATE founder_sim_jobs SET completed_cycles=?,updated_at=? WHERE id=? AND shop_id=?",
                    (completed, core.now_iso(), job_id, shop_id),
                )
                progress_conn.commit()
            finally:
                progress_conn.close()

        done_conn = core.connect()
        try:
            now = core.now_iso()
            core.db_execute(
                done_conn,
                "UPDATE founder_sim_jobs SET status='COMPLETED',completed_cycles=?,updated_at=?,finished_at=? WHERE id=? AND shop_id=?",
                (completed, now, now, job_id, shop_id),
            )
            done_conn.commit()
        finally:
            done_conn.close()
    except Exception as exc:
        fail_conn = core.connect()
        try:
            now = core.now_iso()
            core.db_execute(
                fail_conn,
                "UPDATE founder_sim_jobs SET status='FAILED',error=?,completed_cycles=?,updated_at=?,finished_at=? WHERE id=? AND shop_id=?",
                (str(exc)[:1200], completed, now, now, job_id, shop_id),
            )
            fail_conn.commit()
        finally:
            fail_conn.close()


def get_job(job_id, shop_id):
    conn = core.connect()
    try:
        ensure_table(conn)
        row = _job_row(conn, job_id, shop_id)
        conn.rollback()
        return dict(row) if row else None
    finally:
        conn.close()
