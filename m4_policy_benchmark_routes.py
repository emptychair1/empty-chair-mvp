"""Authenticated M4 pairwise-policy benchmark routes for Crybaby founder lab."""

from fastapi import BackgroundTasks, Form, Request
from fastapi.responses import JSONResponse

import app as core
import m4_decision_policy as policy
import m4_policy_benchmark_jobs as benchmark_jobs
from founder_simulation_safety import FounderSimulationSafetyError

app = core.app


def _user(request):
    user = core.get_current_user(request)
    if not user:
        return None, JSONResponse({"error": "Sign in first."}, status_code=401)
    return user, None


@app.post("/api/m4-policy/benchmark-job")
def start_policy_benchmark(
    request: Request,
    background_tasks: BackgroundTasks,
    cycles: int = Form(250),
):
    user, error = _user(request)
    if error:
        return error
    try:
        job_id, created = benchmark_jobs.create_job(user["shop_id"], cycles)
        if created:
            background_tasks.add_task(benchmark_jobs.run_job, job_id, user["shop_id"])
        return JSONResponse(
            {
                "ok": True,
                "job_id": job_id,
                "started": created,
                "cycles_per_policy": max(20, min(int(cycles), 500)),
                "message": "M4 policy benchmark started." if created else "A policy benchmark is already running.",
            },
            headers={"Cache-Control": "no-store"},
        )
    except FounderSimulationSafetyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})


@app.get("/api/m4-policy/benchmark-status")
def policy_benchmark_status(request: Request, job_id: str):
    user, error = _user(request)
    if error:
        return error
    try:
        job = benchmark_jobs.get_job(job_id, user["shop_id"])
        if not job:
            return JSONResponse({"error": "Policy benchmark job not found."}, status_code=404)
        return JSONResponse({"ok": True, "job": job}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})


@app.get("/api/m4-policy/latest")
def latest_policy_benchmark(request: Request):
    user, error = _user(request)
    if error:
        return error
    try:
        result = policy.latest_benchmark(user["shop_id"])
        return JSONResponse({"ok": True, "benchmark": result}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
