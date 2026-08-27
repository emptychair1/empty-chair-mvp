"""Authenticated routes for fast M4 V1 synthetic training."""
from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse

import app as core
import m4_v1_training_jobs as jobs
from founder_simulation_safety import FounderSimulationSafetyError

app = core.app


def _user(request):
    user = core.get_current_user(request)
    if not user:
        return None, JSONResponse({"error": "Sign in first."}, status_code=401)
    return user, None


@app.post("/api/m4-v1/train-job")
def start_training(request: Request, background_tasks: BackgroundTasks):
    user, error = _user(request)
    if error:
        return error
    try:
        job_id, created = jobs.create_job(user["shop_id"])
        if created:
            background_tasks.add_task(jobs.run_job, job_id, user["shop_id"])
        return JSONResponse({
            "ok": True,
            "job_id": job_id,
            "started": created,
            "message": "Fast M4 V1 training started." if created else "M4 V1 training is already running.",
            "dataset": {"train": 750000, "validation": 125000, "holdout": 125000},
        }, headers={"Cache-Control": "no-store"})
    except FounderSimulationSafetyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})


@app.get("/api/m4-v1/train-status")
def training_status(request: Request, job_id: str):
    user, error = _user(request)
    if error:
        return error
    try:
        job = jobs.get_job(job_id, user["shop_id"])
        if not job:
            return JSONResponse({"error": "M4 V1 training job not found."}, status_code=404)
        return JSONResponse({"ok": True, "job": job}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
