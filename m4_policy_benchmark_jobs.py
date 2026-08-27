"""Background jobs for M4 policy A/B benchmarks."""

from __future__ import annotations

import json
import uuid

import app as core
import m4_decision_policy as policy
from founder_simulation_safety import load_and_assert_founder_simulation_target


def ensure_table(conn):
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS founder_sim_policy_benchmark_jobs (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            cycles INTEGER NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT,
            error TEXT,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        )
        """,
    )


def create_job(shop_id, cycles=250):
    cycles = max(20, min(int(cycles), 500))
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_table(conn)
        running = core.db_fetchone(
            conn,
            "SELECT id FROM founder_sim_policy_benchmark_jobs WHERE shop_id=? AND status='RUNNING' ORDER BY started_at DESC LIMIT 1",
            (shop_id,),
        )
        if running:
            conn.rollback()
            return str(running["id"]), False
        job_id = "founder_sim_policy_job_" + uuid.uuid4().hex
        now = core.now_iso()
        core.db_execute(
            conn,
            """INSERT INTO founder_sim_policy_benchmark_jobs(
                id,shop_id,cycles,status,result_json,error,started_at,updated_at,finished_at
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (job_id, shop_id, cycles, "RUNNING", None, None, now, now, None),
        )
        conn.commit()
        return job_id, True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_job(job_id, shop_id):
    conn = core.connect()
    try:
        ensure_table(conn)
        row = core.db_fetchone(
            conn,
            "SELECT * FROM founder_sim_policy_benchmark_jobs WHERE id=? AND shop_id=?",
            (job_id, shop_id),
        )
        if not row or row["status"] != "RUNNING":
            conn.rollback()
            return
        cycles = int(row["cycles"])
        conn.rollback()
    finally:
        conn.close()

    try:
        result = policy.run_benchmark(shop_id, cycles=cycles)
        done = core.connect()
        try:
            now = core.now_iso()
            core.db_execute(
                done,
                """UPDATE founder_sim_policy_benchmark_jobs
                   SET status='COMPLETED',result_json=?,updated_at=?,finished_at=?
                   WHERE id=? AND shop_id=?""",
                (json.dumps(result), now, now, job_id, shop_id),
            )
            done.commit()
        finally:
            done.close()
    except Exception as exc:
        failed = core.connect()
        try:
            now = core.now_iso()
            core.db_execute(
                failed,
                """UPDATE founder_sim_policy_benchmark_jobs
                   SET status='FAILED',error=?,updated_at=?,finished_at=?
                   WHERE id=? AND shop_id=?""",
                (str(exc)[:1200], now, now, job_id, shop_id),
            )
            failed.commit()
        finally:
            failed.close()


def get_job(job_id, shop_id):
    conn = core.connect()
    try:
        ensure_table(conn)
        row = core.db_fetchone(
            conn,
            "SELECT * FROM founder_sim_policy_benchmark_jobs WHERE id=? AND shop_id=?",
            (job_id, shop_id),
        )
        conn.rollback()
        if not row:
            return None
        result = dict(row)
        if result.get("result_json"):
            result["result"] = json.loads(result["result_json"])
        result.pop("result_json", None)
        return result
    finally:
        conn.close()
