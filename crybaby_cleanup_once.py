"""One-time Crybaby Tattoos production cleanup.

This module is intentionally narrow: it only targets the Crybaby founder shop,
keeps the founder's real artist record, and removes clearly synthetic/test
records. It records completion in the database so restarts are idempotent.
"""

from __future__ import annotations

import json

import app as core
from founder_simulation_safety import load_and_assert_founder_simulation_target

CLEANUP_KEY = "crybaby_live_cleanup_v1"
SIM_PREFIX = "founder_sim_"


def _table_exists(conn, table_name: str) -> bool:
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


def _ensure_audit_table(conn) -> None:
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS maintenance_runs (
            id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            summary_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """,
    )


def _normalized(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _as_dict(row):
    return dict(row) if row is not None else None


def _find_crybaby_shop(conn):
    rows = [
        _as_dict(row)
        for row in core.db_fetchall(
            conn,
            "SELECT id,name FROM shops WHERE LOWER(name) IN ('crybaby tattoos','crybaby tattoo')",
        )
    ]
    if len(rows) != 1:
        raise RuntimeError(
            f"Crybaby cleanup refused: expected exactly one Crybaby shop, found {len(rows)}"
        )
    shop = rows[0]
    load_and_assert_founder_simulation_target(
        conn,
        core.db_fetchone,
        shop["id"],
    )
    return shop


def _resolve_founder_artist(conn, shop_id: str):
    users = [
        _as_dict(row)
        for row in core.db_fetchall(
            conn,
            "SELECT id,name,email FROM users WHERE shop_id=? AND is_active=1 ORDER BY created_at ASC",
            (shop_id,),
        )
    ]
    artists = [
        _as_dict(row)
        for row in core.db_fetchall(
            conn,
            "SELECT id,name,email FROM artists WHERE shop_id=? ORDER BY id",
            (shop_id,),
        )
    ]

    if not users:
        raise RuntimeError(
            "Crybaby cleanup refused: no active Crybaby user account found"
        )

    matches = []
    for artist in artists:
        artist_name = _normalized(artist.get("name"))
        artist_email = _normalized(artist.get("email"))
        for user in users:
            user_name = _normalized(user.get("name"))
            user_email = _normalized(user.get("email"))
            if artist_email and user_email and artist_email == user_email:
                matches.append(artist)
                break
            if artist_name and user_name and artist_name == user_name:
                matches.append(artist)
                break
            if artist_name in {"josh daniels", "joshua daniels"}:
                matches.append(artist)
                break

    unique_matches = {row["id"]: row for row in matches}
    if len(unique_matches) == 1:
        return next(iter(unique_matches.values()))
    if len(unique_matches) > 1:
        raise RuntimeError(
            "Crybaby cleanup refused: multiple founder artist matches found"
        )

    non_sim = [
        row
        for row in artists
        if not str(row["id"] or "").startswith(SIM_PREFIX)
        and not str(row["id"] or "").lower().startswith(("test_", "demo_"))
    ]
    if len(non_sim) == 1:
        return non_sim[0]
    if len(non_sim) > 1:
        raise RuntimeError(
            "Crybaby cleanup refused: founder artist is ambiguous"
        )

    user = users[0]
    artist_id = "artist_crybaby_founder"
    core.db_execute(
        conn,
        """
        INSERT INTO artists(id,shop_id,name,email,phone,styles,services,active)
        VALUES (?,?,?,?,?,?,?,1)
        """,
        (
            artist_id,
            shop_id,
            user["name"],
            user.get("email"),
            None,
            "",
            "tattoo",
        ),
    )
    return {
        "id": artist_id,
        "name": user["name"],
        "email": user.get("email"),
    }


def _customer_is_test(row) -> bool:
    row = _as_dict(row)
    customer_id = str(row.get("id") or "").lower()
    name = _normalized(row.get("name"))
    email = _normalized(row.get("email"))
    phone = str(row.get("phone") or "").strip().lower()

    if customer_id.startswith((SIM_PREFIX, "test_", "demo_")):
        return True
    if name.startswith("sim customer "):
        return True
    if name in {
        "test",
        "test customer",
        "demo customer",
        "simulation customer",
    }:
        return True
    if name.startswith("test ") or name.startswith("demo test "):
        return True
    if email.endswith("@example.test") or email.endswith(".test"):
        return True
    if phone.startswith("+155500"):
        return True
    return False


def _lead_is_test(row, test_customer_ids: set[str]) -> bool:
    row = _as_dict(row)
    lead_id = str(row.get("id") or "").lower()
    source = _normalized(row.get("source"))
    customer_id = str(row.get("customer_id") or "")

    if customer_id in test_customer_ids:
        return True
    if lead_id.startswith((SIM_PREFIX, "test_", "demo_")):
        return True
    if source in {
        "founder_simulation",
        "simulation",
        "sim",
        "test",
        "demo",
    }:
        return True

    try:
        profile = json.loads(row.get("profile_json") or "{}")
    except Exception:
        profile = {}
    return profile.get("synthetic") is True or profile.get("test") is True


def _delete_by_ids(conn, table: str, column: str, ids: list[str]) -> int:
    if not ids or not _table_exists(conn, table):
        return 0
    marks = ",".join("?" for _ in ids)
    cursor = core.db_execute(
        conn,
        f"DELETE FROM {table} WHERE {column} IN ({marks})",
        ids,
    )
    return int(getattr(cursor, "rowcount", 0) or 0)


def run_once() -> dict:
    conn = core.connect()
    try:
        _ensure_audit_table(conn)
        existing = core.db_fetchone(
            conn,
            "SELECT id,summary_json FROM maintenance_runs WHERE id=?",
            (CLEANUP_KEY,),
        )
        if existing:
            existing = _as_dict(existing)
            try:
                return json.loads(existing.get("summary_json") or "{}")
            except Exception:
                return {"status": "already_completed"}

        shop = _find_crybaby_shop(conn)
        shop_id = shop["id"]
        founder_artist = _resolve_founder_artist(conn, shop_id)
        keep_artist_id = founder_artist["id"]

        artist_rows = [
            _as_dict(row)
            for row in core.db_fetchall(
                conn,
                "SELECT id,name FROM artists WHERE shop_id=?",
                (shop_id,),
            )
        ]
        remove_artist_ids = [
            row["id"] for row in artist_rows if row["id"] != keep_artist_id
        ]

        opening_ids = []
        if remove_artist_ids and _table_exists(conn, "openings"):
            marks = ",".join("?" for _ in remove_artist_ids)
            opening_ids = [
                _as_dict(row)["id"]
                for row in core.db_fetchall(
                    conn,
                    f"SELECT id FROM openings WHERE shop_id=? AND artist_id IN ({marks})",
                    [shop_id, *remove_artist_ids],
                )
            ]

        if opening_ids:
            if (
                _table_exists(conn, "google_booking_events")
                and _table_exists(conn, "bookings")
            ):
                marks = ",".join("?" for _ in opening_ids)
                core.db_execute(
                    conn,
                    f"""
                    DELETE FROM google_booking_events
                    WHERE booking_id IN (
                        SELECT id FROM bookings
                        WHERE opening_id IN ({marks})
                    )
                    """,
                    opening_ids,
                )
            _delete_by_ids(conn, "bookings", "opening_id", opening_ids)
            _delete_by_ids(conn, "offers", "opening_id", opening_ids)
            _delete_by_ids(conn, "openings", "id", opening_ids)

        if remove_artist_ids and _table_exists(
            conn,
            "artist_calendar_connections",
        ):
            _delete_by_ids(
                conn,
                "artist_calendar_connections",
                "artist_id",
                remove_artist_ids,
            )
        if remove_artist_ids and _table_exists(
            conn,
            "founder_sim_artist_portfolios",
        ):
            _delete_by_ids(
                conn,
                "founder_sim_artist_portfolios",
                "artist_id",
                remove_artist_ids,
            )
        removed_artists = _delete_by_ids(
            conn,
            "artists",
            "id",
            remove_artist_ids,
        )

        customer_rows = core.db_fetchall(
            conn,
            "SELECT id,name,phone,email FROM customers WHERE shop_id=?",
            (shop_id,),
        )
        test_customer_ids = {
            _as_dict(row)["id"]
            for row in customer_rows
            if _customer_is_test(row)
        }

        lead_rows = []
        if _table_exists(conn, "concierge_leads"):
            lead_rows = core.db_fetchall(
                conn,
                """
                SELECT id,customer_id,source,profile_json
                FROM concierge_leads
                WHERE shop_id=?
                """,
                (shop_id,),
            )
        test_lead_ids = [
            _as_dict(row)["id"]
            for row in lead_rows
            if _lead_is_test(row, test_customer_ids)
        ]
        removed_leads = _delete_by_ids(
            conn,
            "concierge_leads",
            "id",
            test_lead_ids,
        )

        test_customer_id_list = sorted(test_customer_ids)
        if test_customer_id_list:
            _delete_by_ids(
                conn,
                "bookings",
                "customer_id",
                test_customer_id_list,
            )
            _delete_by_ids(
                conn,
                "offers",
                "customer_id",
                test_customer_id_list,
            )
        removed_customers = _delete_by_ids(
            conn,
            "customers",
            "id",
            test_customer_id_list,
        )

        for table in (
            "founder_sim_customer_learning",
            "founder_sim_outcomes",
            "founder_sim_metrics",
            "founder_sim_recommendations",
            "founder_sim_runs",
        ):
            if _table_exists(conn, table):
                core.db_execute(
                    conn,
                    f"DELETE FROM {table} WHERE shop_id=?",
                    (shop_id,),
                )

        if _table_exists(conn, "events"):
            core.db_execute(
                conn,
                "DELETE FROM events WHERE entity_id LIKE ?",
                (SIM_PREFIX + "%",),
            )

        summary = {
            "status": "completed",
            "shop_id": shop_id,
            "shop_name": shop["name"],
            "kept_artist_id": keep_artist_id,
            "kept_artist_name": founder_artist["name"],
            "removed_artists": removed_artists,
            "removed_test_customers": removed_customers,
            "removed_test_concierge_leads": removed_leads,
            "removed_artist_openings": len(opening_ids),
        }
        core.db_execute(
            conn,
            """
            INSERT INTO maintenance_runs(id,scope,summary_json,created_at)
            VALUES (?,?,?,?)
            """,
            (
                CLEANUP_KEY,
                "crybaby",
                json.dumps(summary),
                core.now_iso(),
            ),
        )
        conn.commit()
        print(
            "Crybaby production cleanup completed:",
            json.dumps(summary, sort_keys=True),
        )
        return summary
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_startup_cleanup() -> None:
    """Run once without ever preventing the production app from starting."""
    try:
        run_once()
    except Exception as exc:
        print(
            "Crybaby production cleanup refused/failed:",
            type(exc).__name__,
            str(exc),
        )


run_startup_cleanup()
