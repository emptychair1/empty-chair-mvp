"""Runtime hardening for the observable M4 operator.

The live demo used to await each ElevenLabs narration request before advancing the
visual recovery state. A slow TTS request therefore made Run Full Recovery appear
to do nothing. This patch keeps narration serialized, but lets the UI advance
immediately and surfaces runtime errors visibly.
"""
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

    # Restore button label after a successful offer is visible.
    old_sent = "offer.classList.add('show');state('Offer sent. Waiting for customer behavior.','acting');await speak('sent')}"
    new_sent = "offer.classList.add('show');state('Offer sent. Waiting for customer behavior.','acting');run.textContent='Run full recovery';await speak('sent')}"
    html = html.replace(old_sent, new_sent)

    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


# Replace the registered FastAPI endpoint in place so the public URL remains the same.
for route in core.app.routes:
    if getattr(route, "path", None) == "/m4-operator-live" and getattr(route, "methods", None) and "GET" in route.methods:
        route.endpoint = _patched
        break
