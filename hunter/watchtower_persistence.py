"""Durable persistence primitives for Hunter Watchtower."""
from __future__ import annotations
import json, os, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from cryptography.fernet import Fernet, InvalidToken
import psycopg
from psycopg.rows import dict_row
DATABASE_URL=os.getenv("WATCHTOWER_DATABASE_URL","").strip(); SESSION_KEY=os.getenv("WATCHTOWER_SESSION_KEY","").strip(); SCHEMA="hunter_watchtower"; SESSION_NAME="instagram_storage_state"
def enabled(): return bool(DATABASE_URL)
def session_enabled(): return enabled() and bool(SESSION_KEY)
def utcnow(): return datetime.now(timezone.utc).isoformat()
def _fernet():
    if not SESSION_KEY: raise RuntimeError("WATCHTOWER_SESSION_KEY is not configured")
    try:return Fernet(SESSION_KEY.encode("ascii"))
    except Exception as exc:raise RuntimeError("WATCHTOWER_SESSION_KEY must be a valid Fernet key") from exc
@contextmanager
def connection()->Iterator[psycopg.Connection]:
    if not DATABASE_URL:raise RuntimeError("WATCHTOWER_DATABASE_URL is not configured")
    with psycopg.connect(DATABASE_URL,autocommit=False,row_factory=dict_row) as conn:yield conn;conn.commit()
def init():
    if not enabled():return
    with connection() as c:
        c.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        c.execute(f"CREATE TABLE IF NOT EXISTS {SCHEMA}.watchtower_jobs (id TEXT PRIMARY KEY,collector TEXT NOT NULL,username TEXT NOT NULL,status TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL,started_at TIMESTAMPTZ,finished_at TIMESTAMPTZ,result_json JSONB,error TEXT)")
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_watchtower_jobs_status_created ON {SCHEMA}.watchtower_jobs(status,created_at)")
        c.execute(f"CREATE TABLE IF NOT EXISTS {SCHEMA}.secure_state (name TEXT PRIMARY KEY,ciphertext BYTEA NOT NULL,updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        c.execute(f"CREATE TABLE IF NOT EXISTS {SCHEMA}.pain_ledger (id BIGSERIAL PRIMARY KEY,username TEXT NOT NULL,collector TEXT NOT NULL,signal_status TEXT NOT NULL,intent_score INTEGER NOT NULL DEFAULT 0,matches JSONB NOT NULL DEFAULT '[]'::jsonb,observed_at TIMESTAMPTZ NOT NULL,job_id TEXT UNIQUE REFERENCES {SCHEMA}.watchtower_jobs(id) ON DELETE SET NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_pain_ledger_username_observed ON {SCHEMA}.pain_ledger(username,observed_at DESC)")
        c.execute(f"CREATE TABLE IF NOT EXISTS {SCHEMA}.targets (username TEXT PRIMARY KEY,enabled BOOLEAN NOT NULL DEFAULT TRUE,interval_minutes INTEGER NOT NULL DEFAULT 60,priority INTEGER NOT NULL DEFAULT 50,source TEXT NOT NULL DEFAULT 'manual',last_queued_at TIMESTAMPTZ,next_observe_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_targets_due ON {SCHEMA}.targets(enabled,next_observe_at,priority DESC)")
        c.execute(f"UPDATE {SCHEMA}.watchtower_jobs SET status='queued',started_at=NULL WHERE status='running'")
def save_session_state(state:dict[str,Any]):
    if not session_enabled():raise RuntimeError("durable encrypted session persistence is not configured")
    ciphertext=_fernet().encrypt(json.dumps(state,separators=(',',':'),ensure_ascii=False).encode())
    with connection() as c:c.execute(f"INSERT INTO {SCHEMA}.secure_state(name,ciphertext,updated_at) VALUES (%s,%s,NOW()) ON CONFLICT(name) DO UPDATE SET ciphertext=EXCLUDED.ciphertext,updated_at=NOW()",(SESSION_NAME,ciphertext))
def load_session_state():
    if not session_enabled():return None
    with connection() as c:row=c.execute(f"SELECT ciphertext FROM {SCHEMA}.secure_state WHERE name=%s",(SESSION_NAME,)).fetchone()
    if not row:return None
    try:payload=json.loads(_fernet().decrypt(bytes(row['ciphertext'])).decode())
    except (InvalidToken,ValueError,UnicodeDecodeError,json.JSONDecodeError) as exc:raise RuntimeError("stored Watchtower session could not be decrypted") from exc
    if not isinstance(payload,dict):raise RuntimeError("stored Watchtower session has invalid shape")
    return payload
def enqueue_job(job_id,collector,username,created_at):
    with connection() as c:c.execute(f"INSERT INTO {SCHEMA}.watchtower_jobs(id,collector,username,status,created_at) VALUES (%s,%s,%s,'queued',%s)",(job_id,collector,username,created_at))
def next_job():
    with connection() as c:
        row=c.execute(f"SELECT * FROM {SCHEMA}.watchtower_jobs WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if row:c.execute(f"UPDATE {SCHEMA}.watchtower_jobs SET status='running',started_at=NOW() WHERE id=%s",(row['id'],))
    return dict(row) if row else None
def finish_job(job_id,result):
    with connection() as c:
        c.execute(f"UPDATE {SCHEMA}.watchtower_jobs SET status='finished',finished_at=NOW(),result_json=%s::jsonb,error=NULL WHERE id=%s",(json.dumps(result,ensure_ascii=False),job_id))
        c.execute(f"INSERT INTO {SCHEMA}.pain_ledger(username,collector,signal_status,intent_score,matches,observed_at,job_id) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT(job_id) DO NOTHING",(result.get('username',''),result.get('collector','instagram_story'),result.get('status','unknown'),int(result.get('intent_score') or 0),json.dumps(result.get('matches') or []),result.get('observed_at') or utcnow(),job_id))
def fail_job(job_id,error):
    with connection() as c:c.execute(f"UPDATE {SCHEMA}.watchtower_jobs SET status='failed',finished_at=NOW(),error=%s WHERE id=%s",(error[:2000],job_id))
def get_job(job_id):
    with connection() as c:row=c.execute(f"SELECT * FROM {SCHEMA}.watchtower_jobs WHERE id=%s",(job_id,)).fetchone()
    return dict(row) if row else None
def list_jobs(limit):
    with connection() as c:rows=c.execute(f"SELECT * FROM {SCHEMA}.watchtower_jobs ORDER BY created_at DESC LIMIT %s",(limit,)).fetchall()
    return [dict(r) for r in rows]
def job_counts():
    with connection() as c:rows=c.execute(f"SELECT status,COUNT(*) count FROM {SCHEMA}.watchtower_jobs GROUP BY status").fetchall()
    return {str(r['status']):int(r['count']) for r in rows}
def upsert_target(username,interval_minutes=60,priority=50,source='manual',enabled=True):
    interval_minutes=max(15,min(int(interval_minutes),1440));priority=max(0,min(int(priority),100))
    with connection() as c:row=c.execute(f"INSERT INTO {SCHEMA}.targets(username,enabled,interval_minutes,priority,source,next_observe_at) VALUES (%s,%s,%s,%s,%s,NOW()) ON CONFLICT(username) DO UPDATE SET enabled=EXCLUDED.enabled,interval_minutes=EXCLUDED.interval_minutes,priority=EXCLUDED.priority,source=EXCLUDED.source,updated_at=NOW() RETURNING *",(username,enabled,interval_minutes,priority,source)).fetchone()
    return dict(row)
def list_targets(limit=500):
    with connection() as c:rows=c.execute(f"SELECT * FROM {SCHEMA}.targets ORDER BY enabled DESC,priority DESC,next_observe_at LIMIT %s",(limit,)).fetchall()
    return [dict(r) for r in rows]
def enqueue_due_targets(limit=25):
    with connection() as c:
        rows=c.execute(f"SELECT * FROM {SCHEMA}.targets WHERE enabled=TRUE AND next_observe_at<=NOW() ORDER BY priority DESC,next_observe_at FOR UPDATE SKIP LOCKED LIMIT %s",(limit,)).fetchall();jobs=[]
        for r in rows:
            jid=str(uuid.uuid4());c.execute(f"INSERT INTO {SCHEMA}.watchtower_jobs(id,collector,username,status,created_at) VALUES (%s,'instagram_story',%s,'queued',NOW())",(jid,r['username']));c.execute(f"UPDATE {SCHEMA}.targets SET last_queued_at=NOW(),next_observe_at=NOW()+(interval_minutes*INTERVAL '1 minute'),updated_at=NOW() WHERE username=%s",(r['username'],));jobs.append({'id':jid,'username':r['username']})
    return jobs
def lead_rankings(limit=100):
    recovery_statuses="'recovery_story_found','recovery_broadcast_channel_found'"
    with connection() as c:rows=c.execute(f"SELECT t.username,t.priority,t.source,COUNT(p.id) observations,COUNT(p.id) FILTER(WHERE p.signal_status IN ({recovery_statuses})) recovery_hits,COALESCE(MAX(p.intent_score),0) peak_intent,MAX(p.observed_at) last_observed_at,MAX(p.observed_at) FILTER(WHERE p.signal_status IN ({recovery_statuses})) last_recovery_at FROM {SCHEMA}.targets t LEFT JOIN {SCHEMA}.pain_ledger p ON p.username=t.username AND p.observed_at>NOW()-INTERVAL '30 days' WHERE t.enabled=TRUE GROUP BY t.username,t.priority,t.source ORDER BY (COUNT(p.id) FILTER(WHERE p.signal_status IN ({recovery_statuses}))*40+COALESCE(MAX(p.intent_score),0)+t.priority/5) DESC,MAX(p.observed_at) DESC NULLS LAST LIMIT %s",(limit,)).fetchall()
    out=[]
    for r in rows:
        d=dict(r);d['hunter_score']=int(d['recovery_hits'])*40+int(d['peak_intent'])+int(d['priority'])//5;d['tier']='HOT' if d['hunter_score']>=70 else 'WARM' if d['hunter_score']>=35 else 'WATCH';out.append(d)
    return out
