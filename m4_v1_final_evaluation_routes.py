"""Authenticated UI/API for the final untouched M4 V1 evaluation."""
from fastapi import BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core
import m4_v1_final_evaluation_jobs as jobs
from founder_simulation_safety import FounderSimulationSafetyError

app = core.app


def _user(request):
    user = core.get_current_user(request)
    if not user:
        return None, JSONResponse({"error": "Sign in first."}, status_code=401)
    return user, None


@app.get("/m4-v1-final-eval", response_class=HTMLResponse)
def final_eval_page(request: Request):
    user = core.get_current_user(request)
    if not user:
        return HTMLResponse("<h2>Sign in first.</h2>", status_code=401)
    return HTMLResponse(r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>M4 V1 Final Evaluation</title><style>body{margin:0;background:#080a08;color:#f2ecde;font-family:system-ui;padding:28px}.wrap{max-width:920px;margin:auto}.k{color:#c7ff3e;font-weight:800;text-transform:uppercase;font-size:12px}.card{margin-top:16px;padding:22px;border:1px solid #3b4035;background:#0d100c}.btn{border:1px solid #c7ff3e;background:#c7ff3e;color:#080a08;padding:12px 16px;font-weight:800;text-transform:uppercase;cursor:pointer}.btn:disabled{opacity:.5}.status{margin-top:16px;padding:16px;border:1px solid #30342d;background:#050705;white-space:pre-wrap;font:12px/1.5 ui-monospace,SFMono-Regular,monospace;overflow:auto}.muted{color:#989d92;line-height:1.55}</style></head><body><div class="wrap"><div class="k">M4 V1 // Final untouched evaluation</div><h1>No retraining. No moving the goalposts.</h1><p class="muted">250,000 brand-new interactions · 12,500 new openings · new synthetic shops and seeds. This loads the model you already trained and compares it with the baseline on exactly the same outcomes.</p><div class="card"><button id="start" class="btn">Run Final Evaluation</button><div id="status" class="status">Loading latest evaluation…</div></div></div><script>(()=>{const b=document.getElementById('start'),s=document.getElementById('status');const show=x=>s.textContent=typeof x==='string'?x:JSON.stringify(x,null,2);async function req(url,opt={}){const r=await fetch(url,{...opt,cache:'no-store'});const j=await r.json();if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j;}async function poll(id){b.disabled=true;for(;;){await new Promise(r=>setTimeout(r,2000));const state=await req('/api/m4-v1/final-eval-status?job_id='+encodeURIComponent(id));const job=state.job;if(job.status==='COMPLETED'){show({ok:true,status:'COMPLETED',result:job.result});b.disabled=false;break;}if(job.status==='FAILED'){show({ok:false,status:'FAILED',error:job.error});b.disabled=false;break;}show({ok:true,status:job.status,job_id:id,message:'Evaluating trained M4 on untouched synthetic shops…'});}}async function loadLatest(){try{const latest=await req('/api/m4-v1/final-eval-latest');const job=latest.job;if(!job){show('Ready. This will not retrain M4.');return;}if(job.status==='RUNNING'){show({ok:true,status:'RUNNING',job_id:job.id,message:'Existing final evaluation is still running…'});poll(job.id);return;}if(job.status==='COMPLETED'){show({ok:true,status:'COMPLETED',result:job.result});return;}show({ok:false,status:job.status,error:job.error||null});}catch(e){show('Ready. '+e.message);}}b.onclick=async()=>{b.disabled=true;try{const start=await req('/api/m4-v1/final-eval-job',{method:'POST'});show(start);poll(start.job_id);}catch(e){show('ERROR: '+e.message);b.disabled=false;}};loadLatest();})();</script></body></html>''', headers={"Cache-Control": "no-store"})


@app.post("/api/m4-v1/final-eval-job")
def start_final_eval(request: Request, background_tasks: BackgroundTasks):
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
            "message": "Final untouched M4 V1 evaluation started." if created else "A final evaluation is already running.",
            "retraining": False,
            "rows": 250000,
            "openings": 12500,
        }, headers={"Cache-Control": "no-store"})
    except FounderSimulationSafetyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})


@app.get("/api/m4-v1/final-eval-status")
def final_eval_status(request: Request, job_id: str):
    user, error = _user(request)
    if error:
        return error
    try:
        job = jobs.get_job(job_id, user["shop_id"])
        if not job:
            return JSONResponse({"error": "Final evaluation job not found."}, status_code=404)
        return JSONResponse({"ok": True, "job": job}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})


@app.get("/api/m4-v1/final-eval-latest")
def final_eval_latest(request: Request):
    user, error = _user(request)
    if error:
        return error
    try:
        return JSONResponse({"ok": True, "job": jobs.latest_job(user["shop_id"])}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
