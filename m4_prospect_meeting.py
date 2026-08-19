"""Dedicated prospect entrypoint for tonight's M4 Meeting.

This uses the Gemini Live prospect mode so the experience does not depend on OpenAI
Realtime credits. It remains isolated from Josh's relationship memory and exposes the
privacy-first Data Gift without making it the center of the encounter.
"""

from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core


@core.app.get("/meet-m4", response_class=HTMLResponse)
def meet_m4(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return HTMLResponse(
        """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>The Meeting</title>
<style>
html,body{margin:0;height:100%;background:#f3f3ef;color:#1b1d19;font-family:system-ui,sans-serif;overflow:hidden}
.shell{height:100%;position:relative;background:#f3f3ef}
iframe{position:absolute;inset:0;width:100%;height:100%;border:0;background:#f3f3ef}
.gift-tab{position:absolute;z-index:4;left:50%;bottom:max(14px,env(safe-area-inset-bottom));transform:translateX(-50%);border:0;background:transparent;color:#8c9087;font:500 10px ui-monospace,monospace;letter-spacing:.08em;cursor:pointer;opacity:.34;padding:10px 16px;transition:opacity .25s ease}
.gift-tab:hover,.gift-tab:focus{opacity:.8}
.gift{position:absolute;inset:0;z-index:8;display:grid;place-items:center;background:rgba(243,243,239,.96);backdrop-filter:blur(8px);opacity:0;visibility:hidden;transition:.3s ease;padding:22px;box-sizing:border-box}
.gift.show{opacity:1;visibility:visible}
.card{width:min(92vw,540px);border:1px solid rgba(31,36,27,.14);background:#f7f7f3;padding:32px 28px;box-sizing:border-box;position:relative}
.close{position:absolute;right:15px;top:12px;border:0;background:transparent;color:#858a80;font:20px Georgia,serif;cursor:pointer}
h2{margin:0 0 12px;font:500 27px/1.15 Georgia,serif}
p{margin:0 0 14px;color:#62675d;font:13px/1.6 system-ui,sans-serif}
.privacy{padding-top:14px;border-top:1px solid rgba(31,36,27,.1);color:#767b71;font:11px/1.55 ui-monospace,monospace}
.pick{display:inline-flex;margin-top:18px;border:1px solid #bec2b8;border-radius:999px;padding:11px 16px;cursor:pointer;font:500 12px system-ui,sans-serif;background:#fbfbf7}.pick input{display:none}
.status{margin-top:12px;min-height:18px;color:#74796f;font:11px/1.5 ui-monospace,monospace}.status.ok{color:#687a1c}.status.error{color:#8d463f}
</style>
</head>
<body>
<main class="shell">
<iframe src="/m4-smooth" title="The Meeting with M4" allow="microphone"></iframe>
<button class="gift-tab" id="giftTab" type="button">DATA GIFT</button>
<section class="gift" id="gift" aria-hidden="true">
  <div class="card">
    <button class="close" id="close" type="button">×</button>
    <h2>A gift, whether we work together or not.</h2>
    <p>If you choose to share a CSV copy of your customer data, Empty Chair can clean and enrich it and return the improved file directly to you.</p>
    <div class="privacy">This application endpoint processes the file in request memory and does not write the raw upload, parsed rows, or enriched result to Empty Chair's database, filesystem, or M4 relationship memory. The response is marked no-store. We do not broaden that into claims about infrastructure or provider retention that we have not independently verified.</div>
    <label class="pick">Choose customer CSV<input id="file" type="file" accept=".csv,text/csv"></label>
    <div class="status" id="status"></div>
  </div>
</section>
</main>
<script>
const gift=document.getElementById('gift'),tab=document.getElementById('giftTab'),close=document.getElementById('close'),file=document.getElementById('file'),status=document.getElementById('status');
function show(){gift.classList.add('show');gift.setAttribute('aria-hidden','false');status.textContent='';status.className='status'}
function hide(){gift.classList.remove('show');gift.setAttribute('aria-hidden','true')}
tab.addEventListener('click',show);close.addEventListener('click',hide);gift.addEventListener('click',e=>{if(e.target===gift)hide()});
file.addEventListener('change',async()=>{const selected=file.files&&file.files[0];if(!selected)return;status.className='status';status.textContent='Enriching…';const form=new FormData();form.append('file',selected);try{const r=await fetch('/api/data-gift/enrich',{method:'POST',body:form,cache:'no-store'});if(!r.ok){let msg='Could not enrich this file.';try{msg=(await r.json()).error||msg}catch(_){}throw new Error(msg)}const blob=await r.blob();let name='empty_chair_enriched.csv';const d=r.headers.get('Content-Disposition')||'';const m=d.match(/filename="?([^";]+)"?/i);if(m)name=m[1];const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);status.className='status ok';status.textContent='Returned directly to you.'}catch(e){status.className='status error';status.textContent=e.message||'Could not enrich this file.'}finally{file.value=''}});
</script>
</body>
</html>"""
    )


@core.app.get("/meet-m4/ready", response_class=HTMLResponse)
def meet_m4_ready(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return HTMLResponse(
        """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>The Meeting</title><style>html,body{margin:0;height:100%;background:#f3f3ef;color:#1b1d19;font-family:system-ui,sans-serif}.wrap{height:100%;display:grid;place-items:center;padding:24px;box-sizing:border-box}.inner{text-align:center;max-width:520px}h1{font:500 30px Georgia,serif;margin:0 0 12px}p{color:#73786f;font:13px/1.6 ui-monospace,monospace;margin:0 0 24px}a{display:inline-block;color:#252821;text-decoration:none;border:1px solid #c8cbc2;border-radius:999px;padding:14px 24px;font:500 19px Georgia,serif}</style></head><body><main class="wrap"><section class="inner"><h1>The Meeting</h1><p>M4 is present on the smooth Gemini path and this first meeting is isolated from the creator relationship.</p><a href="/meet-m4">Enter</a></section></main></body></html>"""
    )
