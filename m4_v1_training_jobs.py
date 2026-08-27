"""Background jobs for fast M4 V1 synthetic training."""
from __future__ import annotations

import json
import uuid

import app as core
import m4_v1_fast_train as trainer
from founder_simulation_safety import load_and_assert_founder_simulation_target


def ensure_table(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS m4_v1_training_jobs (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT,
            error TEXT,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        )
    """)


def create_job(shop_id):
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_table(conn)
        running = core.db_fetchone(conn, "SELECT id FROM m4_v1_training_jobs WHERE shop_id=? AND status='RUNNING' ORDER BY started_at DESC LIMIT 1", (shop_id,))
        if running:
            conn.rollback()
            return str(running["id"]), False
        job_id = "m4_v1_training_job_" + uuid.uuid4().hex
        now = core.now_iso()
        core.db_execute(conn, "INSERT INTO m4_v1_training_jobs(id,shop_id,status,result_json,error,started_at,updated_at,finished_at) VALUES (?,?,?,?,?,?,?,?)", (job_id, shop_id, "RUNNING", None, None, now, now, None))
        conn.commit()
        return job_id, True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_job(job_id, shop_id):
    try:
        result = trainer.run_training(shop_id)
        conn = core.connect()
        try:
            now = core.now_iso()
            core.db_execute(conn, "UPDATE m4_v1_training_jobs SET status='COMPLETED',result_json=?,updated_at=?,finished_at=? WHERE id=? AND shop_id=?", (json.dumps(result), now, now, job_id, shop_id))
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        conn = core.connect()
        try:
            now = core.now_iso()
            core.db_execute(conn, "UPDATE m4_v1_training_jobs SET status='FAILED',error=?,updated_at=?,finished_at=? WHERE id=? AND shop_id=?", (str(exc)[:1800], now, now, job_id, shop_id))
            conn.commit()
        finally:
            conn.close()


def _row_to_job(row):
    if not row:
        return None
    result = dict(row)
    if result.get("result_json"):
        result["result"] = json.loads(result["result_json"])
    result.pop("result_json", None)
    return result


def get_job(job_id, shop_id):
    conn = core.connect()
    try:
        ensure_table(conn)
        row = core.db_fetchone(conn, "SELECT * FROM m4_v1_training_jobs WHERE id=? AND shop_id=?", (job_id, shop_id))
        conn.rollback()
        return _row_to_job(row)
    finally:
        conn.close()


def latest_job(shop_id):
    """Return the latest persisted training job for this shop, including result."""
    conn = core.connect()
    try:
        ensure_table(conn)
        row = core.db_fetchone(
            conn,
            "SELECT * FROM m4_v1_training_jobs WHERE shop_id=? ORDER BY started_at DESC LIMIT 1",
            (shop_id,),
        )
        conn.rollback()
        return _row_to_job(row)
    finally:
        conn.close()
