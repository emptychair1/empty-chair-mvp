"""Isolate Empty Chair 2.0 data from the legacy 1.x Postgres tables.

The production DATABASE_URL is intentionally reused, but 2.0 has a different schema.
All 2.0 queries run with search_path=emptychair_v2 so table names such as artists,
clients, and bookings cannot collide with the old application.
"""
from __future__ import annotations

import sqlite3

import v2_app as core

PG_SCHEMA = "emptychair_v2"


class V2DB:
    def __init__(self):
        self.pg = bool(core.DATABASE_URL)
        if self.pg:
            import psycopg2
            import psycopg2.extras

            # Neon production may sit behind transaction pooling. Session-level SET
            # state is not safe across commits there, so CREATE/SET and the caller's
            # query intentionally remain in the SAME transaction. The helper that
            # owns this connection commits only after its actual query completes.
            self.raw = psycopg2.connect(core.DATABASE_URL)
            self.dict_cursor = psycopg2.extras.RealDictCursor
            cur = self.raw.cursor()
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA}")
            cur.execute(f"SET LOCAL search_path TO {PG_SCHEMA}")
        else:
            self.raw = sqlite3.connect(core.SQLITE_PATH, check_same_thread=False)
            self.raw.row_factory = sqlite3.Row
            self.dict_cursor = None

    def execute(self, q, params=()):
        if self.pg:
            cur = self.raw.cursor(cursor_factory=self.dict_cursor)
            q = q.replace("?", "%s")
        else:
            cur = self.raw.cursor()
        cur.execute(q, params)
        return cur

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()


# All 2.0 modules access core.DB dynamically. Replace it before social auth and the
# worker initialize, then create the clean 2.0 tables inside the isolated schema.
core.DB = V2DB
core.init_db()
print(f"Empty Chair 2.0 database namespace loaded: {PG_SCHEMA if core.DATABASE_URL else 'sqlite'}", flush=True)
