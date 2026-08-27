"""Authenticated controls for the Crybaby founder simulation."""

from fastapi import Form, Request
from fastapi.responses import JSONResponse

import app as core
import m4_founder_simulation_engine as engine
from founder_simulation_safety import (
    FounderSimulationSafetyError,
    load_and_assert_founder_simulation_target,
)

app = core.app

RESET_TEMPORARILY_DISABLED = True


def _user(request):
    user = core.get_current_user(request)
    if not user:
        return None, JSONResponse({"error": "Sign in first."}, status_code=401)
    return user, None


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


def _set_read_timeout(conn):
    if getattr(core, "USE_POSTGRES", False):
        core.db_execute(conn, "SET LOCAL statement_timeout = '2500ms'")
        core.db_execute(conn, "SET LOCAL lock_timeout = '1000ms'")


def _set_write_timeout(conn):
    if getattr(core, "USE_POSTGRES", False):
        core.db_execute(conn, "SET LOCAL statement_timeout = '5000ms'")
        core.db_execute(conn, "SET LOCAL lock_timeout = '1500ms'")


def _ensure_founder_support_tables(conn):
    engine.ensure_tables(conn)
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS founder_sim_artist_portfolios (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            artist_id TEXT NOT NULL,
            profile_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """,
    )
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS founder_sim_runs (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            seed_version TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
    )


@app.post("/api/founder-sim/initialize")
def founder_sim_initialize(request: Request):
    user, error = _user(request)
    if error:
        return error

    conn = core.connect()
    try:
        _set_write_timeout(conn)
        load_and_assert_founder_simulation_target(
            conn,
            core.db_fetchone,
            user["shop_id"],
        )
        _ensure_founder_support_tables(conn)
        conn.commit()
        return JSONResponse(
            {
                "ok": True,
                "initialized": True,
                "message": "Founder simulation tables initialized. No shop, customer, lead, artist, opening, or booking data was changed.",
                "reset_enabled": False,
            },
            headers={"Cache-Control": "no-store"},
        )
    except FounderSimulationSafetyError as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return JSONResponse(
            {"error": str(exc)},
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return JSONResponse(
            {"error": f"Founder simulation initialization unavailable: {exc}"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    finally:
        conn.close()


@app.post("/api/founder-sim/reset")
def founder_sim_reset(request: Request):
    user, error = _user(request)
    if error:
        return error

    if RESET_TEMPORARILY_DISABLED:
        return JSONResponse(
            {
                "error": "Founder simulation reset is temporarily disabled while the reset path is being hardened. No data was changed by this request."
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    return JSONResponse(
        {"error": "Founder simulation reset unavailable."},
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/founder-sim/run")
def founder_sim_run(request: Request, cycles: int = Form(30)):
    user, error = _user(request)
    if error:
        return error
    try:
        result = engine.run_simulation(user["shop_id"], cycles=max(1, min(int(cycles), 365)))
        recommendation = engine.latest_recommendation(user["shop_id"])
        return JSONResponse(
            {"ok": True, "result": result, "recommendation": recommendation},
            headers={"Cache-Control": "no-store"},
        )
    except FounderSimulationSafetyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})


@app.get("/api/founder-sim/status")
def founder_sim_status(request: Request):
    user, error = _user(request)
    if error:
        return error

    conn = core.connect()
    try:
        _set_read_timeout(conn)

        required_tables = (
            "founder_sim_metrics",
            "founder_sim_customer_learning",
            "founder_sim_recommendations",
            "founder_sim_artist_portfolios",
            "founder_sim_runs",
        )
        missing = [table for table in required_tables if not _table_exists(conn, table)]
        if missing:
            conn.rollback()
            return JSONResponse(
                {
                    "ok": True,
                    "initialized": False,
                    "latest_metric": None,
                    "customers_with_learning": 0,
                    "recommendation": None,
                    "reset_enabled": False,
                    "message": "Founder simulation has not been initialized yet.",
                    "missing_tables": missing,
                },
                headers={"Cache-Control": "no-store"},
            )

        latest_metric = core.db_fetchone(
            conn,
            "SELECT * FROM founder_sim_metrics WHERE shop_id=? ORDER BY cycle DESC LIMIT 1",
            (user["shop_id"],),
        )
        learning_count = core.db_fetchone(
            conn,
            "SELECT COUNT(*) AS n FROM founder_sim_customer_learning WHERE shop_id=?",
            (user["shop_id"],),
        )
        recommendation_row = core.db_fetchone(
            conn,
            "SELECT * FROM founder_sim_recommendations WHERE shop_id=? ORDER BY created_at DESC LIMIT 1",
            (user["shop_id"],),
        )
        conn.rollback()

        return JSONResponse(
            {
                "ok": True,
                "initialized": True,
                "latest_metric": dict(latest_metric) if latest_metric else None,
                "customers_with_learning": int(learning_count["n"]) if learning_count else 0,
                "recommendation": dict(recommendation_row) if recommendation_row else None,
                "reset_enabled": False,
            },
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return JSONResponse(
            {"error": f"Founder simulation status unavailable: {exc}"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    finally:
        conn.close()
