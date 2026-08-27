"""Crybaby Tattoos founder simulation reset + deterministic seed.

This module never resets a shop until founder_simulation_safety has verified
that the target is Crybaby Tattoos and is not a protected shop such as
Blindwolf Tattoo. The shop row and user/founder accounts are deliberately
preserved.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import app as core
from founder_simulation_safety import load_and_assert_founder_simulation_target


SIM_PREFIX = "founder_sim_"


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


def _ensure_simulation_tables(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS founder_sim_artist_portfolios (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            artist_id TEXT NOT NULL,
            profile_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
    """)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS founder_sim_runs (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            seed_version TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)


def _delete_opening_dependents(conn, opening_ids):
    if not opening_ids:
        return
    marks = ",".join("?" for _ in opening_ids)
    if _table_exists(conn, "google_booking_events"):
        core.db_execute(
            conn,
            f"DELETE FROM google_booking_events WHERE booking_id IN (SELECT id FROM bookings WHERE opening_id IN ({marks}))",
            opening_ids,
        )
    if _table_exists(conn, "bookings"):
        core.db_execute(conn, f"DELETE FROM bookings WHERE opening_id IN ({marks})", opening_ids)
    if _table_exists(conn, "offers"):
        core.db_execute(conn, f"DELETE FROM offers WHERE opening_id IN ({marks})", opening_ids)


def _reset_shop_data(conn, shop_id):
    """Delete Crybaby child/simulation data only. Never delete shops/users."""
    opening_ids = []
    artist_ids = []
    customer_ids = []

    if _table_exists(conn, "openings"):
        opening_ids = [
            row["id"]
            for row in core.db_fetchall(conn, "SELECT id FROM openings WHERE shop_id=?", (shop_id,))
        ]
    if _table_exists(conn, "artists"):
        artist_ids = [
            row["id"]
            for row in core.db_fetchall(conn, "SELECT id FROM artists WHERE shop_id=?", (shop_id,))
        ]
    if _table_exists(conn, "customers"):
        customer_ids = [
            row["id"]
            for row in core.db_fetchall(conn, "SELECT id FROM customers WHERE shop_id=?", (shop_id,))
        ]

    _delete_opening_dependents(conn, opening_ids)

    # Tables with direct shop ownership.
    direct_shop_tables = (
        "concierge_leads",
        "autopilot_campaigns",
        "founder_sim_artist_portfolios",
        "founder_sim_runs",
    )
    for table in direct_shop_tables:
        if _table_exists(conn, table):
            if table == "autopilot_campaigns" and _table_exists(conn, "autopilot_campaign_openings"):
                core.db_execute(
                    conn,
                    "DELETE FROM autopilot_campaign_openings WHERE campaign_id IN (SELECT id FROM autopilot_campaigns WHERE shop_id=?)",
                    (shop_id,),
                )
            core.db_execute(conn, f"DELETE FROM {table} WHERE shop_id=?", (shop_id,))

    if _table_exists(conn, "openings"):
        core.db_execute(conn, "DELETE FROM openings WHERE shop_id=?", (shop_id,))

    if artist_ids and _table_exists(conn, "artist_calendar_connections"):
        marks = ",".join("?" for _ in artist_ids)
        core.db_execute(conn, f"DELETE FROM artist_calendar_connections WHERE artist_id IN ({marks})", artist_ids)

    if _table_exists(conn, "artists"):
        core.db_execute(conn, "DELETE FROM artists WHERE shop_id=?", (shop_id,))

    if _table_exists(conn, "customers"):
        core.db_execute(conn, "DELETE FROM customers WHERE shop_id=?", (shop_id,))

    # Events do not currently carry shop_id. Remove only founder simulation
    # entities, never broad shop/customer history from another tenant.
    if _table_exists(conn, "events"):
        core.db_execute(conn, "DELETE FROM events WHERE entity_id LIKE ?", (SIM_PREFIX + "%",))


def _seed_artists(conn, shop_id, now):
    artists = [
        ("founder_sim_artist_ava", "Ava Mercer", "American Traditional, Neo Traditional", "bold lines,color,flash,animals"),
        ("founder_sim_artist_milo", "Milo Graves", "Blackwork, Geometric", "blackwork,geometry,ornamental,high contrast"),
        ("founder_sim_artist_june", "June Vale", "Fine Line, Floral", "fine line,botanical,delicate,small-medium"),
        ("founder_sim_artist_roman", "Roman Cross", "Black and Grey, Realism", "realism,portrait,black grey,large scale"),
        ("founder_sim_artist_nova", "Nova Reed", "Illustrative, Neo Traditional", "illustrative,color,whimsical,medium-large"),
    ]
    for artist_id, name, styles, portfolio_traits in artists:
        core.db_execute(
            conn,
            "INSERT INTO artists(id,shop_id,name,email,phone,styles,services,active) VALUES (?,?,?,?,?,?,?,1)",
            (artist_id, shop_id, name, None, None, styles, "tattoo"),
        )
        profile = {
            "synthetic": True,
            "styles": [item.strip() for item in styles.split(",")],
            "portfolio_traits": [item.strip() for item in portfolio_traits.split(",")],
            "sample_count": 24,
            "consistency": 0.82,
        }
        core.db_execute(
            conn,
            "INSERT INTO founder_sim_artist_portfolios(id,shop_id,artist_id,profile_json,created_at) VALUES (?,?,?,?,?)",
            (SIM_PREFIX + "portfolio_" + artist_id.split("_")[-1], shop_id, artist_id, json.dumps(profile), now),
        )
    return artists


def _seed_customers(conn, shop_id, now):
    styles = ["American Traditional", "Blackwork", "Fine Line", "Realism", "Neo Traditional"]
    artists = [
        "founder_sim_artist_ava",
        "founder_sim_artist_milo",
        "founder_sim_artist_june",
        "founder_sim_artist_roman",
        "founder_sim_artist_nova",
    ]
    seeded = []
    for index in range(1, 51):
        customer_id = f"{SIM_PREFIX}customer_{index:03d}"
        style = styles[(index - 1) % len(styles)]
        artist_id = artists[(index - 1) % len(artists)]
        spend = 180 + ((index * 37) % 720)
        completed = index % 7
        cancellations = 1 if index % 13 == 0 else 0
        no_shows = 1 if index % 29 == 0 else 0
        consent = 0 if index % 11 == 0 else 1
        core.db_execute(
            conn,
            """INSERT INTO customers(
                id,shop_id,name,phone,email,communication_consent,
                preferred_artists,preferred_styles,preferred_services,
                appointment_count,completed_count,cancellation_count,no_show_count,
                average_spend,last_appointment_at,last_offer_at,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                customer_id, shop_id, f"Sim Customer {index:03d}", f"+155500{index:04d}",
                f"sim{index:03d}@example.test", consent, artist_id, style, "tattoo",
                completed + cancellations + no_shows, completed, cancellations, no_shows,
                spend, None, None, now, now,
            ),
        )
        seeded.append(customer_id)
    return seeded


def _seed_concierge_leads(conn, shop_id, customer_ids, now):
    if not _table_exists(conn, "concierge_leads"):
        return 0
    count = 0
    for index, customer_id in enumerate(customer_ids[:15], start=1):
        profile = {
            "synthetic": True,
            "project": "Synthetic founder simulation tattoo request",
            "budget": 250 + index * 25,
            "timing": "short_notice" if index % 3 == 0 else "flexible",
            "placement": ["forearm", "upper arm", "calf", "thigh", "back"][index % 5],
            "travel": [10, 20, 35, 50][index % 4],
            "short_notice": index % 3 == 0,
            "offer_opt_in": True,
        }
        core.db_execute(
            conn,
            """INSERT INTO concierge_leads(
                id,shop_id,customer_id,source,profile_json,m4_confidence,
                offer_opt_in,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                f"{SIM_PREFIX}lead_{index:03d}", shop_id, customer_id, "founder_simulation",
                json.dumps(profile), 55 + (index * 3) % 40, 1, now, now,
            ),
        )
        count += 1
    return count


def _seed_openings(conn, shop_id, now):
    today = date.today()
    rows = [
        ("founder_sim_opening_001", "founder_sim_artist_ava", today + timedelta(days=1), "13:00", "16:00", "American Traditional", 450),
        ("founder_sim_opening_002", "founder_sim_artist_milo", today + timedelta(days=2), "14:00", "17:00", "Blackwork", 500),
        ("founder_sim_opening_003", "founder_sim_artist_june", today + timedelta(days=3), "11:00", "14:00", "Fine Line", 350),
        ("founder_sim_opening_004", "founder_sim_artist_roman", today + timedelta(days=4), "12:00", "17:00", "Realism", 800),
        ("founder_sim_opening_005", "founder_sim_artist_nova", today + timedelta(days=5), "15:00", "18:00", "Neo Traditional", 550),
    ]
    expires_at = (today + timedelta(days=7)).isoformat() + "T23:59:00+00:00"
    for opening_id, artist_id, day, start, end, style, price in rows:
        core.db_execute(
            conn,
            """INSERT INTO openings(
                id,shop_id,artist_id,date,start_time,end_time,service,style,price,status,created_at,expires_at
            ) VALUES (?,?,?,?,?,?,?,?,?,'OPEN',?,?)""",
            (opening_id, shop_id, artist_id, day.isoformat(), start, end, "tattoo", style, price, now, expires_at),
        )
    return len(rows)


def reset_and_seed_crybaby(shop_id):
    """Reset and deterministically seed the configured Crybaby founder sandbox.

    Returns a small summary suitable for logs/UI. No mutation occurs until the
    target shop has passed the safety boundary.
    """
    conn = core.connect()
    try:
        # Critical ordering: validate before CREATE/DELETE/INSERT mutation.
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        _ensure_simulation_tables(conn)
        _reset_shop_data(conn, shop_id)

        now = core.now_iso()
        artists = _seed_artists(conn, shop_id, now)
        customers = _seed_customers(conn, shop_id, now)
        lead_count = _seed_concierge_leads(conn, shop_id, customers, now)
        opening_count = _seed_openings(conn, shop_id, now)
        run_id = SIM_PREFIX + "run_v1"
        core.db_execute(
            conn,
            "INSERT INTO founder_sim_runs(id,shop_id,seed_version,created_at) VALUES (?,?,?,?)",
            (run_id, shop_id, "v1", now),
        )
        conn.commit()
        return {
            "shop_id": shop_id,
            "seed_version": "v1",
            "artists": len(artists),
            "customers": len(customers),
            "concierge_leads": lead_count,
            "openings": opening_count,
            "founder_account_preserved": True,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
