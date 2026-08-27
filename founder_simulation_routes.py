"""Authenticated controls for the Crybaby founder simulation."""

from fastapi import Form, Request
from fastapi.responses import JSONResponse

import app as core
import m4_founder_simulation_engine as engine
from founder_simulation_safety import FounderSimulationSafetyError

app = core.app

RESET_TEMPORARILY_DISABLED = True


def _user(request):
    user = core.get_current_user(request)
    if not user:
        return None, JSONResponse({"error": "Sign in first."}, status_code=401)
    return user, None


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
        engine.ensure_tables(conn)
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
        recommendation = engine.latest_recommendation(user["shop_id"])
        return JSONResponse(
            {
                "ok": True,
                "latest_metric": dict(latest_metric) if latest_metric else None,
                "customers_with_learning": int(learning_count["n"]) if learning_count else 0,
                "recommendation": recommendation,
                "reset_enabled": False,
            },
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
    finally:
        conn.close()
