"""Runtime hardening and owner-facing confidence UI for the observable M4 operator."""
from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import m4_operator_observable


_original = m4_operator_observable.m4_operator_live


def _patched(request: Request):
    response = _original(request)
    if not isinstance(response, HTMLResponse):
        return response
    html = response.body.decode("utf-8")

    old = "async function speak(key){try{const f=new FormData();f.append('key',key);const r=await fetch('/api/m4/operator/narrate',{method:'POST',body:f,cache:'no-store'}),j=await r.json();if(j.text)log.textContent+='\\nM4: '+j.text;if(j.audio_base64){voiceStatus.textContent='M4 is speaking';await new Promise(resolve=>{const a=new Audio('data:audio/mpeg;base64,'+j.audio_base64);a.onended=resolve;a.onerror=resolve;a.play().catch(resolve)})}else{voiceStatus.textContent='M4 voice unavailable; narration shown as text.'}}catch(e){voiceStatus.textContent='M4 voice unavailable; narration shown as text.'}}"
    new = "let voiceQueue=Promise.resolve();async function speakNow(key){try{const f=new FormData();f.append('key',key);const ctl=new AbortController();const timer=setTimeout(()=>ctl.abort(),6500);const r=await fetch('/api/m4/operator/narrate',{method:'POST',body:f,cache:'no-store',signal:ctl.signal});clearTimeout(timer);const j=await r.json();if(j.text)log.textContent+='\\nM4: '+j.text;if(j.audio_base64){voiceStatus.textContent='M4 is speaking';await new Promise(resolve=>{const a=new Audio('data:audio/mpeg;base64,'+j.audio_base64);const done=()=>resolve();a.onended=done;a.onerror=done;setTimeout(done,12000);a.play().catch(done)})}else{voiceStatus.textContent='M4 narration shown as text.'}}catch(e){voiceStatus.textContent='Voice delayed; M4 is continuing.'}}function speak(key){voiceQueue=voiceQueue.then(()=>speakNow(key)).catch(()=>{});return new Promise(resolve=>setTimeout(resolve,180))}"
    html = html.replace(old, new)

    old_run = "run.onclick=async()=>{run.disabled=true;offer.classList.remove('show');"
    new_run = "run.onclick=async()=>{run.disabled=true;run.textContent='M4 RUNNING…';state('Recovery run started','acting');offer.classList.remove('show');"
    html = html.replace(old_run, new_run)

    old_catch = "catch(e){state('Interrupted: '+e.message,'');run.disabled=false}};load().catch(e=>{log.textContent=e.message;run.disabled=true})"
    new_catch = "catch(e){state('Interrupted: '+(e&&e.message?e.message:String(e)),'');voiceStatus.textContent='Recovery stopped — see M4 log.';run.disabled=false;run.textContent='Run full recovery'}};load().then(()=>{run.textContent='Run full recovery'}).catch(e=>{log.textContent='M4 load error: '+(e&&e.message?e.message:String(e));m4state.textContent='operator unavailable';run.disabled=false;run.textContent='Retry full recovery'})"
    html = html.replace(old_catch, new_catch)

    old_sent = "offer.classList.add('show');state('Offer sent. Waiting for customer behavior.','acting');await speak('sent')}"
    new_sent = "offer.classList.add('show');state('Offer sent. Waiting for customer behavior.','acting');run.textContent='Run full recovery';await speak('sent')}"
    html = html.replace(old_sent, new_sent)

    confidence_css = r'''
    .person{position:relative}.m4-confidence{display:inline-flex;align-items:center;gap:6px;margin-top:9px;padding:5px 8px;border:1px solid #455045;font:900 9px ui-monospace,monospace;letter-spacing:.08em}.m4-confidence.high{border-color:var(--g);color:var(--g);background:rgba(166,255,46,.06)}.m4-confidence.medium{border-color:#d8b65a;color:#e4c871}.m4-confidence.low{border-color:#b96565;color:#e39191}.m4-action{margin-left:6px;color:#aab2a6}.m4-explain{margin-top:10px;padding-top:9px;border-top:1px solid #273127}.m4-explain b{font:800 8px ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:#879483}.m4-explain ul{list-style:none;padding:0;margin:6px 0 0}.m4-explain li{font-size:10px;line-height:1.45;color:#c8d2c3;margin:3px 0}.m4-explain li.good:before{content:'+ ';color:var(--g);font-weight:900}.m4-explain li.risk:before{content:'− ';color:#e39191;font-weight:900}.m4-learning{margin-top:8px;padding:7px 8px;border-left:2px solid #d8b65a;background:#11130e;color:#c9bea0;font-size:9px;line-height:1.45}.person.focus .m4-explain{display:block}.m4-owner-callout{margin-top:10px;color:#a6ff2e;font:800 9px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em}
    '''
    html = html.replace("</style>", confidence_css + "</style>")

    old_card = "function card(c){const d=document.createElement('div');d.className='person';d.dataset.id=c.customer_id;d.innerHTML=`<b>${c.name||c.customer_id}</b><span>booking ${Math.round(c.booking_probability*100)}% · uplift ${Math.round(c.incremental_uplift*100)}%</span><span class=\"score\">queue ${c.queue_score} · EV $${Number(c.expected_value||0).toFixed(0)}</span>`;return d}"
    new_card = "function card(c){const d=document.createElement('div');d.className='person';d.dataset.id=c.customer_id;const label=(c.m4_confidence_label||'LOW').toLowerCase(),score=Number(c.m4_confidence_score||0),action=c.recommended_action==='ACT'?'ACT':c.recommended_action==='RECOMMEND'?'RECOMMEND':'LEARN FIRST';const why=(c.why_this_person||[]).slice(0,4).map(x=>`<li class=\"good\">${x}</li>`).join('');const risks=(c.risk_factors||[]).slice(0,2).map(x=>`<li class=\"risk\">${x}</li>`).join('');const missing=(c.missing_high_value_signals||[]).slice(0,3);const learn=missing.length?`<div class=\"m4-learning\"><b>M4 WANTS TO LEARN:</b> ${missing.join(' · ')}</div>`:'';d.innerHTML=`<b>${c.name||c.customer_id}</b><span>booking ${Math.round(c.booking_probability*100)}% · uplift ${Math.round(c.incremental_uplift*100)}%</span><span class=\"score\">queue ${c.queue_score} · EV $${Number(c.expected_value||0).toFixed(0)}</span><div class=\"m4-confidence ${label}\">${(c.m4_confidence_label||'LOW')} ${score}% <span class=\"m4-action\">→ ${action}</span></div><div class=\"m4-explain\"><b>Why M4 ranks this person</b><ul>${why||'<li>Limited supporting evidence</li>'}${risks}</ul>${learn}</div>`;return d}"
    html = html.replace(old_card, new_card)

    old_top = "top=ranked[0];document.getElementById('mev').textContent='$'+Number(top.expected_value||0).toFixed(0);document.getElementById('mscore').textContent=top.queue_score;"
    new_top = "top=ranked[0];document.getElementById('mev').textContent='$'+Number(top.expected_value||0).toFixed(0);document.getElementById('mscore').textContent=top.queue_score;log.textContent+='\\n\\nOWNER VIEW // '+(top.m4_confidence_label||'LOW')+' CONFIDENCE '+Number(top.m4_confidence_score||0)+'% → '+(top.recommended_action||'LEARN_OR_FALLBACK');if((top.why_this_person||[]).length)log.textContent+='\\nWHY: '+top.why_this_person.slice(0,3).join(' • ');if((top.risk_factors||[]).length)log.textContent+='\\nRISK: '+top.risk_factors.slice(0,2).join(' • ');"
    html = html.replace(old_top, new_top)

    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


for route in core.app.routes:
    if getattr(route, "path", None) == "/m4-operator-live" and getattr(route, "methods", None) and "GET" in route.methods:
        route.endpoint = _patched
        break
