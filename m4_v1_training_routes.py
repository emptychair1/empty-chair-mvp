"""Authenticated routes for fast M4 V1 synthetic training."""
from fastapi import BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core
import m4_v1_training_jobs as jobs
from founder_simulation_safety import FounderSimulationSafetyError

app = core.app


def _user(request):
    user = core.get_current_user(request)
    if not user:
        return None, JSONResponse({"error": "Sign in first."}, status_code=401)
    return user, None


@app.get("/m4-v1-train", response_class=HTMLResponse)
def training_page(request: Request):
    user = core.get_current_user(request)
    if not user:
        return HTMLResponse("<h2>Sign in first.</h2>", status_code=401)
    return HTMLResponse(r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>M4 V1 Fast Train</title><style>body{margin:0;background:#080a08;color:#f2ecde;font-family:system-ui;padding:28px}.wrap{max-width:900px;margin:auto}.k{color:#c7ff3e;font-weight:800;text-transform:uppercase;font-size:12px}.card{margin-top:16px;padding:22px;border:1px solid #3b4035;background:#0d100c}.btn{border:1px solid #c7ff3e;background:#c7ff3e;color:#080a08;padding:12px 16px;font-weight:800;text-transform:uppercase;cursor:pointer}.btn:disabled{opacity:.5}.status{margin-top:16px;padding:16px;border:1px solid #30342d;background:#050705;white-space:pre-wrap;font:12px/1.5 ui-monospace,SFMono-Regular,monospace;overflow:auto}.muted{color:#989d92;line-height:1.55}</style></head><body><div class="wrap"><div class="k">M4 V1 // Fast training</div><h1>1,000,000 synthetic interactions</h1><p class="muted">750,000 train · 125,000 validation · 125,000 sealed holdout. This is the fast pass/fail run before scaling further.</p><div class="card"><button id="start" class="btn">Start Fast Train</button><div id="status" class="status">Ready.</div></div></div><script>(()=>{const b=document.getElementById('start'),s=document.getElementById('status');const show=x=>s.textContent=typeof x==='string'?x:JSON.stringify(x,null,2);async function req(url,opt={}){const r=await fetch(url,{...opt,cache:'no-store'});const j=await r.json();if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j;}b.onclick=async()=>{b.disabled=true;try{const start=await req('/api/m4-v1/train-job',{method:'POST'});show(start);const id=start.job_id;for(;;){await new Promise(r=>setTimeout(r,2000));const state=await req('/api/m4-v1/train-status?job_id='+encodeURIComponent(id));const job=state.job;if(job.status==='COMPLETED'){show({ok:true,status:'COMPLETED',result:job.result});break;}if(job.status==='FAILED'){show({ok:false,status:'FAILED',error:job.error});break;}show({ok:true,status:job.status,job_id:id,message:'Training M4 V1 against the frozen simulator…'});}}catch(e){show('ERROR: '+e.message);}finally{b.disabled=false;}}})();</script></body></html>''', headers={"Cache-Control": "no-store"})


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
