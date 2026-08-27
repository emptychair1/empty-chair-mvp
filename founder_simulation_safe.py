"""Bounded founder simulation reset for production.

Keeps the existing Crybaby-only safety boundary and seed helpers, but adds
PostgreSQL lock/statement timeouts plus progress logging so a reset cannot hang
shop reads indefinitely.
"""

from __future__ import annotations

import app as core
import founder_simulation as sim
from founder_simulation_safety import load_and_assert_founder_simulation_target


def _set_transaction_timeouts(conn):
    if not getattr(core, "USE_POSTGRES", False):
        return
    # LOCAL settings apply only to this transaction and disappear on commit or
    # rollback. Keep them deliberately short because this is a tiny synthetic
    # founder dataset, not a bulk migration.
    core.db_execute(conn, "SET LOCAL lock_timeout = '3000ms'")
    core.db_execute(conn, "SET LOCAL statement_timeout = '15000ms'")


def reset_and_seed_crybaby(shop_id):
    conn = core.connect()
    try:
        print(f"Founder sim reset start shop_id={shop_id}", flush=True)
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        _set_transaction_timeouts(conn)

        print("Founder sim: ensure tables", flush=True)
        sim._ensure_simulation_tables(conn)

        print("Founder sim: reset Crybaby-scoped data", flush=True)
        sim._reset_shop_data(conn, shop_id)

        now = core.now_iso()
        print("Founder sim: seed artists", flush=True)
        artists = sim._seed_artists(conn, shop_id, now)

        print("Founder sim: seed customers", flush=True)
        customers = sim._seed_customers(conn, shop_id, now)

        print("Founder sim: seed concierge leads", flush=True)
        lead_count = sim._seed_concierge_leads(conn, shop_id, customers, now)

        print("Founder sim: seed openings", flush=True)
        opening_count = sim._seed_openings(conn, shop_id, now)

        run_id = sim.SIM_PREFIX + "run_v1"
        core.db_execute(
            conn,
            "INSERT INTO founder_sim_runs(id,shop_id,seed_version,created_at) VALUES (?,?,?,?)",
            (run_id, shop_id, "v1", now),
        )
        conn.commit()
        print("Founder sim reset complete", flush=True)
        return {
            "shop_id": shop_id,
            "seed_version": "v1",
            "artists": len(artists),
            "customers": len(customers),
            "concierge_leads": lead_count,
            "openings": opening_count,
            "founder_account_preserved": True,
        }
    except Exception as exc:
        try:
            conn.rollback()
        finally:
            print(f"Founder sim reset failed: {type(exc).__name__}: {exc}", flush=True)
        raise
    finally:
        conn.close()
