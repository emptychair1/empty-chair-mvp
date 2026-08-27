"""Authenticated routes for Simulation V3 M4 stress benchmark."""

from fastapi import BackgroundTasks, Form, Request
from fastapi.responses import JSONResponse

import app as core
import m4_stress_benchmark_jobs as jobs
import m4_stress_benchmark_v3 as stress
import m4_v1_training_routes  # noqa: F401,E402
import m4_v1_final_evaluation_routes  # noqa: F401,E402
from founder_simulation_safety import FounderSimulationSafetyError

app = core.app


def _user(request):
    user = core.get_current_user(request)
    if not user:
        return None, JSONResponse({"error": "Sign in first."}, status_code=401)
    return user, None


@app.post("/api/m4-stress/benchmark-job")
def start_stress_benchmark(
    request: Request,
    background_tasks: BackgroundTasks,
    cycles: int = Form(250),
):
    user, error = _user(request)
    if error:
        return error
    try:
        job_id, created = jobs.create_job(user["shop_id"], cycles)
        if created:
            background_tasks.add_task(jobs.run_job, job_id, user["shop_id"])
        return JSONResponse(
            {
                "ok": True,
                "job_id": job_id,
                "started": created,
                "cycles_per_policy": max(50, min(int(cycles), 500)),
                "environment": "v3-adversarial",
                "message": "M4 V3 stress benchmark started." if created else "A V3 stress benchmark is already running.",
            },
            headers={"Cache-Control": "no-store"},
        )
    except FounderSimulationSafetyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})


@app.get("/api/m4-stress/benchmark-status")
def stress_benchmark_status(request: Request, job_id: str):
    user, error = _user(request)
    if error:
        return error
    try:
        job = jobs.get_job(job_id, user["shop_id"])
        if not job:
            return JSONResponse({"error": "V3 stress benchmark job not found."}, status_code=404)
        return JSONResponse({"ok": True, "job": job}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})


@app.get("/api/m4-stress/latest")
def latest_stress_benchmark(request: Request):
    user, error = _user(request)
    if error:
        return error
    try:
        result = stress.latest_benchmark(user["shop_id"])
        return JSONResponse({"ok": True, "benchmark": result}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
