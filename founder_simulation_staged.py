"""Staged, Crybaby-only founder simulation reset and seed.

Only rows created by the founder simulator (founder_sim_*) are deleted. The
Crybaby shop row, users/founder accounts, and all non-simulation Crybaby data
are preserved. Blindwolf remains protected by founder_simulation_safety.
"""

from __future__ import annotations

import app as core
import founder_simulation as seed
import m4_founder_simulation_engine as engine
from founder_simulation_safety import load_and_assert_founder_simulation_target

SIM_PREFIX = "founder_sim_"


def _timeout(conn):
    if getattr(core, "USE_POSTGRES", False):
        core.db_execute(conn, "SET LOCAL statement_timeout = '5000ms'")
        core.db_execute(conn, "SET LOCAL lock_timeout = '1500ms'")


def _table_exists(conn, table_name):
    if getattr(core, "USE_POSTGRES", False):
        row = core.db_fetchone(
            conn,
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=?",
            (table_name,),
        )
        return bool(row)
    row = core.db_fetchone(
        conn,
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return bool(row)


def _stage(shop_id, name, fn):
    conn = core.connect()
    try:
        _timeout(conn)
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        result = fn(conn)
        conn.commit()
        print(f"Founder simulation stage complete: {name}", flush=True)
        return result
    except Exception:
        conn.rollback()
        print(f"Founder simulation stage failed: {name}", flush=True)
        raise
    finally:
        conn.close()


def _clear_learning(conn, shop_id):
    engine.ensure_tables(conn)
    seed._ensure_simulation_tables(conn)
    for table in (
        "founder_sim_customer_learning",
        "founder_sim_outcomes",
        "founder_sim_metrics",
        "founder_sim_recommendations",
        "founder_sim_artist_portfolios",
        "founder_sim_runs",
    ):
        if _table_exists(conn, table):
            core.db_execute(conn, f"DELETE FROM {table} WHERE shop_id=?", (shop_id,))
    return True


def _clear_openings(conn, shop_id):
    if not _table_exists(conn, "openings"):
        return 0
    ids = [
        row["id"]
        for row in core.db_fetchall(
            conn,
            "SELECT id FROM openings WHERE shop_id=? AND id LIKE ?",
            (shop_id, SIM_PREFIX + "%"),
        )
    ]
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    if _table_exists(conn, "google_booking_events") and _table_exists(conn, "bookings"):
        core.db_execute(
            conn,
            f"DELETE FROM google_booking_events WHERE booking_id IN (SELECT id FROM bookings WHERE opening_id IN ({marks}))",
            ids,
        )
    if _table_exists(conn, "bookings"):
        core.db_execute(conn, f"DELETE FROM bookings WHERE opening_id IN ({marks})", ids)
    if _table_exists(conn, "offers"):
        core.db_execute(conn, f"DELETE FROM offers WHERE opening_id IN ({marks})", ids)
    core.db_execute(
        conn,
        "DELETE FROM openings WHERE shop_id=? AND id LIKE ?",
        (shop_id, SIM_PREFIX + "%"),
    )
    return len(ids)


def _clear_leads(conn, shop_id):
    if not _table_exists(conn, "concierge_leads"):
        return 0
    cur = core.db_execute(
        conn,
        "DELETE FROM concierge_leads WHERE shop_id=? AND id LIKE ?",
        (shop_id, SIM_PREFIX + "%"),
    )
    return max(0, int(cur.rowcount or 0))


def _clear_customers(conn, shop_id):
    if not _table_exists(conn, "customers"):
        return 0
    cur = core.db_execute(
        conn,
        "DELETE FROM customers WHERE shop_id=? AND id LIKE ?",
        (shop_id, SIM_PREFIX + "%"),
    )
    return max(0, int(cur.rowcount or 0))


def _clear_artists(conn, shop_id):
    if not _table_exists(conn, "artists"):
        return 0
    ids = [
        row["id"]
        for row in core.db_fetchall(
            conn,
            "SELECT id FROM artists WHERE shop_id=? AND id LIKE ?",
            (shop_id, SIM_PREFIX + "%"),
        )
    ]
    if ids and _table_exists(conn, "artist_calendar_connections"):
        marks = ",".join("?" for _ in ids)
        core.db_execute(
            conn,
            f"DELETE FROM artist_calendar_connections WHERE artist_id IN ({marks})",
            ids,
        )
    core.db_execute(
        conn,
        "DELETE FROM artists WHERE shop_id=? AND id LIKE ?",
        (shop_id, SIM_PREFIX + "%"),
    )
    return len(ids)


def _seed_artists(conn, shop_id, now):
    return len(seed._seed_artists(conn, shop_id, now))


def _seed_customers(conn, shop_id, now):
    return seed._seed_customers(conn, shop_id, now)


def _seed_leads(conn, shop_id, customer_ids, now):
    return seed._seed_concierge_leads(conn, shop_id, customer_ids, now)


def _seed_openings(conn, shop_id, now):
    return seed._seed_openings(conn, shop_id, now)


def reset_and_seed_crybaby_staged(shop_id):
    """Reset only founder_sim_* rows in short committed stages, then reseed."""

    _stage(shop_id, "clear_learning", lambda conn: _clear_learning(conn, shop_id))
    removed_openings = _stage(shop_id, "clear_openings", lambda conn: _clear_openings(conn, shop_id))
    removed_leads = _stage(shop_id, "clear_leads", lambda conn: _clear_leads(conn, shop_id))
    removed_customers = _stage(shop_id, "clear_customers", lambda conn: _clear_customers(conn, shop_id))
    removed_artists = _stage(shop_id, "clear_artists", lambda conn: _clear_artists(conn, shop_id))

    now = core.now_iso()
    artist_count = _stage(shop_id, "seed_artists", lambda conn: _seed_artists(conn, shop_id, now))
    customer_ids = _stage(shop_id, "seed_customers", lambda conn: _seed_customers(conn, shop_id, now))
    lead_count = _stage(shop_id, "seed_leads", lambda conn: _seed_leads(conn, shop_id, customer_ids, now))
    opening_count = _stage(shop_id, "seed_openings", lambda conn: _seed_openings(conn, shop_id, now))

    def write_run(conn):
        core.db_execute(
            conn,
            "INSERT INTO founder_sim_runs(id,shop_id,seed_version,created_at) VALUES (?,?,?,?)",
            (SIM_PREFIX + "run_v2", shop_id, "v2-staged", now),
        )
        return True

    _stage(shop_id, "record_run", write_run)

    return {
        "shop_id": shop_id,
        "seed_version": "v2-staged",
        "artists": artist_count,
        "customers": len(customer_ids),
        "concierge_leads": lead_count,
        "openings": opening_count,
        "removed_previous_simulation": {
            "artists": removed_artists,
            "customers": removed_customers,
            "leads": removed_leads,
            "openings": removed_openings,
        },
        "founder_account_preserved": True,
        "non_simulation_crybaby_data_preserved": True,
        "blindwolf_untouched": True,
    }
