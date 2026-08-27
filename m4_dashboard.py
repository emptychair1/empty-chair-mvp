import json
import os
import urllib.error
import urllib.parse
import urllib.request

from fastapi import Request
from fastapi.responses import HTMLResponse, Response, JSONResponse

import app as core
import m4_runtime
import m4_founder_simulation_engine as founder_engine
import founder_simulation_routes  # noqa: F401,E402
import m4_policy_benchmark_routes  # noqa: F401,E402

app = core.app
M4_VOICE_ID = os.getenv("M4_ELEVENLABS_VOICE_ID", "Ss7hQAiJNG6a81OU5k51")
M4_VOICE_MODEL = os.getenv("M4_ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")


def _is_crybaby(shop):
    name = " ".join(str((shop or {}).get("name") or "").strip().lower().split())
    return name in {"crybaby tattoo", "crybaby tattoos"}


def _founder_controls_html():
    return r'''
<style>
.founder-sim{margin-top:18px;padding:20px;border:1px solid #c7ff3e;background:#0b0e0a;box-shadow:4px 4px 0 #000}.founder-sim h2{margin:6px 0 8px;color:#f2ecde;font:400 30px var(--cartoon);text-transform:uppercase}.founder-sim p{margin:0;color:#9da198;font-size:12px;line-height:1.55}.founder-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.founder-actions button{appearance:none;border:1px solid #3d4138;background:#141812;color:#f2ecde;padding:10px 13px;font:400 12px var(--cartoon);text-transform:uppercase;cursor:pointer}.founder-actions button.primary{background:#c7ff3e;color:#0b0e0a;border-color:#c7ff3e}.founder-actions button.decision{border-color:#c7ff3e;color:#c7ff3e}.founder-actions button:disabled{opacity:.5;cursor:wait}.founder-status{margin-top:14px;padding:12px;border:1px solid #30342d;background:#080a08;color:#b9bdb3;font:11px/1.55 ui-monospace,SFMono-Regular,monospace;white-space:pre-wrap}.founder-warning{margin-top:10px;color:#7f857a;font-size:10px}.founder-warning b{color:#c7ff3e}
</style>
<section class="founder-sim" id="founderSim">
  <div class="m4-kicker">Founder Simulation // Crybaby Tattoos</div>
  <h2>Controlled M4 Lab</h2>
  <p>Long simulations and policy benchmarks execute as background jobs. The new decision policy learns relative customer ordering from historical outcomes, then competes against legacy M4 on identical future synthetic outcomes.</p>
  <div class="founder-actions">
    <button class="primary" id="simInit" type="button">Initialize Simulation</button>
    <button id="simReset" type="button">Reset + Seed Crybaby</button>
    <button id="sim1" type="button">Run 1 Cycle</button>
    <button id="sim30" type="button">Run 30 Cycles</button>
    <button id="sim180" type="button">Run 180 Cycles</button>
    <button class="decision" id="simBenchmark" type="button">Benchmark New M4</button>
    <button id="simStatus" type="button">Refresh Status</button>
  </div>
  <div class="founder-status" id="founderStatus">Ready. No simulation request runs automatically.</div>
  <div class="founder-warning"><b>Benchmark:</b> 250 synthetic cycles per policy. Compares top-1, top-3, recovered revenue, contacts per booking, and revenue per contact. <b>Safety:</b> Blindwolf remains protected server-side.</div>
</section>
<script>
(()=>{
 const box=document.getElementById('founderStatus');
 const buttons=[...document.querySelectorAll('#founderSim button')];
 const setBusy=v=>buttons.forEach(b=>b.disabled=v);
 const show=v=>{box.textContent=typeof v==='string'?v:JSON.stringify(v,null,2)};
 async function jsonFetch(url,opts={}){
   const controller=new AbortController();
   const timer=setTimeout(()=>controller.abort(),15000);
   try{
     const r=await fetch(url,{...opts,signal:controller.signal,cache:'no-store'});
     const text=await r.text();
     let j={};
     try{j=text?JSON.parse(text):{};}catch(_){throw new Error('Invalid server response');}
     if(!r.ok)throw new Error(j.error||('HTTP '+r.status));
     return j;
   } finally { clearTimeout(timer); }
 }
 async function call(url,cycles){
   setBusy(true); show('Running…');
   try{
     const opts={method:'POST'};
     if(cycles){const f=new FormData();f.append('cycles',String(cycles));opts.body=f;}
     const j=await jsonFetch(url,opts); show(j);
   }catch(e){show('ERROR: '+(e.name==='AbortError'?'request timed out':(e.message||e)));}
   finally{setBusy(false);}
 }
 async function runJob(total){
   setBusy(true);
   try{
     const f=new FormData(); f.append('cycles',String(total));
     const started=await jsonFetch('/api/founder-sim/run-job',{method:'POST',body:f});
     const jobId=started.job_id;
     show({message:started.message,job_id:jobId,progress:'0/'+total});
     for(;;){
       await new Promise(resolve=>setTimeout(resolve,1000));
       const state=await jsonFetch('/api/founder-sim/job-status?job_id='+encodeURIComponent(jobId));
       const job=state.job;
       show({job_id:job.id,status:job.status,progress:job.completed_cycles+'/'+job.requested_cycles,error:job.error||null});
       if(job.status==='COMPLETED'){
         const status=await jsonFetch('/api/founder-sim/status');
         show({ok:true,job:job,status:status});
         break;
       }
       if(job.status==='FAILED') break;
     }
   }catch(e){
     show('ERROR: '+(e.name==='AbortError'?'request timed out':(e.message||e)));
   }finally{setBusy(false);}
 }
 async function benchmark(){
   setBusy(true);
   try{
     const f=new FormData(); f.append('cycles','250');
     const started=await jsonFetch('/api/m4-policy/benchmark-job',{method:'POST',body:f});
     const jobId=started.job_id;
     show({message:started.message,job_id:jobId,benchmark:'legacy vs decision',cycles_per_policy:250,status:'RUNNING'});
     for(;;){
       await new Promise(resolve=>setTimeout(resolve,1000));
       const state=await jsonFetch('/api/m4-policy/benchmark-status?job_id='+encodeURIComponent(jobId));
       const job=state.job;
       if(job.status==='COMPLETED'){
         show({ok:true,status:'COMPLETED',result:job.result});
         break;
       }
       if(job.status==='FAILED'){
         show({ok:false,status:'FAILED',error:job.error});
         break;
       }
       show({job_id:job.id,status:job.status,cycles_per_policy:job.cycles,message:'Training pairwise ranking + evaluating both policies…'});
     }
   }catch(e){
     show('ERROR: '+(e.name==='AbortError'?'request timed out':(e.message||e)));
   }finally{setBusy(false);}
 }
 async function status(){
   setBusy(true); show('Loading status…');
   try{show(await jsonFetch('/api/founder-sim/status'));}
   catch(e){show('ERROR: '+(e.name==='AbortError'?'request timed out':(e.message||e)));}
   finally{setBusy(false);}
 }
 document.getElementById('simInit').onclick=()=>call('/api/founder-sim/initialize');
 document.getElementById('simReset').onclick=()=>call('/api/founder-sim/reset');
 document.getElementById('sim1').onclick=()=>call('/api/founder-sim/run',1);
 document.getElementById('sim30').onclick=()=>runJob(30);
 document.getElementById('sim180').onclick=()=>runJob(180);
 document.getElementById('simBenchmark').onclick=benchmark;
 document.getElementById('simStatus').onclick=status;
})();
</script>
'''


@app.get('/m4', response_class=HTMLResponse)
def m4_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        if getattr(core, "USE_POSTGRES", False):
            core.db_execute(conn, "SET LOCAL statement_timeout = '5000ms'")
            core.db_execute(conn, "SET LOCAL lock_timeout = '2000ms'")
        shop_row = core.db_fetchone(conn, 'SELECT * FROM shops WHERE id=? LIMIT 1', (user['shop_id'],))
        shop = dict(shop_row) if shop_row else None
        customers = [dict(r) for r in core.db_fetchall(conn, 'SELECT * FROM customers WHERE shop_id=?', (user['shop_id'],))]
        openings = [dict(r) for r in core.db_fetchall(conn, "SELECT o.*,a.name AS artist_name FROM openings o JOIN artists a ON a.id=o.artist_id WHERE o.shop_id=? AND o.status IN ('OPEN','RECOVERY_ACTIVE','NO_RECOVERY') ORDER BY o.date,o.start_time", (user['shop_id'],))]
    finally:
        conn.close()

    live = openings[0] if openings else None
    ranked = m4_runtime.rank(customers, live, 10) if live else []
    consented = sum(1 for c in customers if c.get('communication_consent'))
    expected = sum(r['expected_value'] for r in ranked)
    avg_conf = sum(r['confidence'] for r in ranked) / len(ranked) if ranked else 0
    styles = {}
    for c in customers:
        if not c.get('communication_consent'):
            continue
        for style in str(c.get('preferred_styles') or '').split(','):
            style = style.strip()
            if style:
                styles[style] = styles.get(style, 0) + 1
    demand = sorted(styles.items(), key=lambda x: x[1], reverse=True)[:8]

    response = core.templates.TemplateResponse(
        request=request,
        name='m4.html',
        context={
            'user': user,
            'shop': shop,
            'opening': live,
            'ranked': ranked,
            'consented': consented,
            'expected': expected,
            'avg_conf': avg_conf,
            'demand': demand,
            'model': m4_runtime.MODEL,
            'recommendation': None,
            'm4_voice_id': M4_VOICE_ID,
        },
    )

    if _is_crybaby(shop):
        html = response.body.decode('utf-8')
        html = html.replace('</body>', _founder_controls_html() + '</body>')
        return HTMLResponse(
            html,
            headers={'Cache-Control': 'no-store, no-cache, must-revalidate'},
        )
    return response


@app.get('/api/m4/recommendation/audio')
def m4_recommendation_audio(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({'error': 'Sign in first.'}, status_code=401)
    try:
        recommendation = founder_engine.latest_recommendation(user['shop_id'])
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=503)
    if not recommendation:
        return JSONResponse({'error': 'M4 has no recommendation to speak yet.'}, status_code=404)
    if not ELEVENLABS_API_KEY:
        return JSONResponse({'error': 'ELEVENLABS_API_KEY is not configured.'}, status_code=503)

    voice_id = recommendation.get('voice_id') or M4_VOICE_ID
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{urllib.parse.quote(voice_id)}?output_format=mp3_44100_128"
    payload = {
        'text': recommendation['recommendation_text'],
        'model_id': M4_VOICE_MODEL,
        'voice_settings': {
            'stability': 0.34,
            'similarity_boost': 0.76,
            'style': 0.48,
            'use_speaker_boost': True,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'xi-api-key': ELEVENLABS_API_KEY, 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            audio = response.read()
        return Response(
            content=audio,
            media_type='audio/mpeg',
            headers={'Cache-Control': 'no-store, no-cache, must-revalidate'},
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        return JSONResponse({'error': f'ElevenLabs HTTP {exc.code}', 'detail': detail[:800]}, status_code=503)
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=503)
