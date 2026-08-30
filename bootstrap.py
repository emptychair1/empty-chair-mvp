"""Explicit production bootstrap for Empty Chair.

Render launches this module so additive routes and notification integrations are
always registered before the ASGI app starts serving requests.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from fastapi import Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core

import features  # noqa: F401,E402
import notifications  # noqa: F401,E402
import delivery_safety  # noqa: F401,E402
import stripe_deposits  # noqa: F401,E402
import google_integration  # noqa: F401,E402
import calendar_safety  # noqa: F401,E402
import claim_flow  # noqa: F401,E402
import booking_confirmation  # noqa: F401,E402
import booking_details  # noqa: F401,E402
import pilot_operations  # noqa: F401,E402
import pilot  # noqa: F401,E402
import pilot_safety  # noqa: F401,E402
import fill_chairs_flow  # noqa: F401,E402
import demo_mode  # noqa: F401,E402
import sales_demo  # noqa: F401,E402
import paid_activation  # noqa: F401,E402
import admin_dashboard  # noqa: F401,E402
import artist_metrics  # noqa: F401,E402
import onboarding  # noqa: F401,E402
import dashboard_metrics  # noqa: F401,E402
import m4_dashboard  # noqa: F401,E402
import m4_integration  # noqa: F401,E402
import m4_operator  # noqa: F401,E402
import m4_operator_demo  # noqa: F401,E402
import m4_operator_observable  # noqa: F401,E402
import m4_operator_desktop_fix  # noqa: F401,E402
import founder_simulation_routes  # noqa: F401,E402
import m4_human_judgment_routes  # noqa: F401,E402
import concierge  # noqa: F401,E402
import attribution_runtime  # noqa: F401,E402
import crybaby_cleanup_once  # noqa: F401,E402
import crybaby_cleanup_fk_patch  # noqa: F401,E402
import customer_bulk_delete  # noqa: F401,E402
import contest  # noqa: F401,E402
import contest_runtime_fix  # noqa: F401,E402
import demand_content  # noqa: F401,E402

meeting_v2 = None
meeting_import_error = None
meeting_v2_visual_patch = None
meeting_v2_visual_refine = None
try:
    import meeting_v2 as _meeting_v2  # noqa: F401,E402
    meeting_v2 = _meeting_v2
    meeting_v2.ELEVENLABS_VOICE_ID = os.getenv("M4_ELEVENLABS_VOICE_ID", "Ss7hQAiJNG6a81OU5k51")
    meeting_v2.ELEVENLABS_MODEL_ID = os.getenv("M4_ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    import meeting_v2_runtime_fix  # noqa: F401,E402
    import meeting_v2_streaming  # noqa: F401,E402
    import meeting_v2_visual_patch as _meeting_v2_visual_patch  # noqa: F401,E402
    meeting_v2_visual_patch = _meeting_v2_visual_patch
    import meeting_v2_visual_refine as _meeting_v2_visual_refine  # noqa: F401,E402
    meeting_v2_visual_refine = _meeting_v2_visual_refine
    import m4_analysis_email  # noqa: F401,E402
except Exception as meeting_exc:  # pragma: no cover
    meeting_import_error = repr(meeting_exc)
    print(f"Meeting v2 disabled: {meeting_exc}")

@core.app.post("/api/meeting-v2/opening")
def meeting_v2_opening(request: Request, session_id: str = Form(...)):
    if meeting_v2 is None:
        return JSONResponse({"error": meeting_import_error or "Meeting unavailable"}, status_code=503)
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    sid = (session_id or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    answer = "I'm M4. Josh gave me a simple job: find something economically useful in your business in about ten minutes. If I can't, you probably don't need him. Tell me a little about the shop."
    try:
        state, turns = meeting_v2._load_session(user, sid)
        if not turns:
            meeting_v2._save_session(user, sid, state, None, answer)
        audio_url = f"/api/meeting-v2/audio/{urllib.parse.quote(sid)}?v={time.time_ns()}"
        return JSONResponse({"ok": True, "session_id": sid, "m4_text": answer, "audio_url": audio_url}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        print(f"Meeting v2 opening failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})

@core.app.get("/api/meeting-v2/voice-debug")
def meeting_v2_voice_debug(request: Request):
    if meeting_v2 is None:
        return JSONResponse({"error": meeting_import_error or "Meeting unavailable"}, status_code=503)
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    voice_id = meeting_v2.ELEVENLABS_VOICE_ID
    model_id = meeting_v2.ELEVENLABS_MODEL_ID
    if not meeting_v2.ELEVENLABS_API_KEY:
        return JSONResponse({"active_voice_id": voice_id, "active_model_id": model_id, "error": "ELEVENLABS_API_KEY is not configured"}, status_code=503)
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/voices/{voice_id}", headers={"xi-api-key": meeting_v2.ELEVENLABS_API_KEY}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return JSONResponse({"active_voice_id": voice_id,"active_model_id": model_id,"elevenlabs_voice_id": payload.get("voice_id"),"name": payload.get("name"),"category": payload.get("category"),"labels": payload.get("labels"),"fine_tuning": payload.get("fine_tuning")}, headers={"Cache-Control":"no-store"})
    except urllib.error.HTTPError as exc:
        detail=exc.read().decode("utf-8",errors="replace")
        return JSONResponse({"active_voice_id":voice_id,"active_model_id":model_id,"error":f"ElevenLabs HTTP {exc.code}","detail":detail[:1000]},status_code=exc.code,headers={"Cache-Control":"no-store"})
    except Exception as exc:
        return JSONResponse({"active_voice_id":voice_id,"active_model_id":model_id,"error":str(exc)},status_code=503,headers={"Cache-Control":"no-store"})

@core.app.get("/meet-m4", response_class=HTMLResponse)
def meet_m4_bootstrap(request: Request):
    if meeting_v2 is not None:
        response=meeting_v2.meeting_v2_page(request)
        if isinstance(response,HTMLResponse):
            html=response.body.decode("utf-8")
            old="async function opening(){busy=true;visual('thinking','Something is already here.');let form=new FormData();form.append('session_id',sessionId);form.append('opening','1');let r=await fetch('/api/meeting-v2/turn',{method:'POST',body:form,cache:'no-store'}),j=await r.json();if(!r.ok)throw Error(j.error||'Could not enter the meeting.');if(j.audio_base64)await play64(j.audio_base64);busy=false}"
            new="async function opening(){busy=true;visual('thinking','Something is already here.');let form=new FormData();form.append('session_id',sessionId);let r=await fetch('/api/meeting-v2/opening',{method:'POST',body:form,cache:'no-store'}),j=await r.json();if(!r.ok)throw Error(j.error||'Could not enter the meeting.');if(j.audio_url)await playUrl(j.audio_url);else if(j.audio_base64)await play64(j.audio_base64);busy=false}"
            html=html.replace(old,new)
            html=html.replace("if(j.audio_base64)await play64(j.audio_base64);", "if(j.audio_url)await playUrl(j.audio_url);else if(j.audio_base64)await play64(j.audio_base64);")
            stream_player="async function playUrl(u){return new Promise(resolve=>{let done=false;const finish=(msg)=>{if(done)return;done=true;presence.style.transform='';visual('listening',msg||'Speak when you are ready.');resolve()};const a=new Audio();a.preload='auto';a.src=u;a.onplaying=()=>visual('speaking','M4 is speaking.');a.onended=()=>finish();a.onerror=()=>finish('Voice stream interrupted. Continue when ready.');const timer=setTimeout(()=>finish('Voice took too long. Continue when ready.'),12000);a.addEventListener('ended',()=>clearTimeout(timer),{once:true});a.addEventListener('error',()=>clearTimeout(timer),{once:true});a.play().catch(()=>finish('Voice playback was blocked. Tap once and continue.'))})}"
            if "function playUrl(" not in html:
                pos=html.rfind("</script>")
                if pos!=-1:
                    html=html[:pos]+stream_player+html[pos:]
            old_opening_catch="catch(e){started=false;enter.classList.remove('hidden');visual('present',e.message||'Microphone or voice service unavailable.')}"
            new_opening_catch="catch(e){started=false;const msg=e.message||'Microphone or voice service unavailable.';if(enter&&enter.parentNode)enter.remove();visual('error',msg);hint.textContent=msg;hint.style.position='relative';hint.style.zIndex='999';hint.style.color='#181b17';hint.style.fontFamily='ui-monospace,SFMono-Regular,monospace';hint.style.fontSize='14px';hint.style.lineHeight='1.5';hint.style.padding='16px 18px';hint.style.background='#fff';hint.style.border='1px solid rgba(30,35,28,.18)';hint.style.borderRadius='12px';hint.style.maxWidth='min(92vw,760px)';hint.style.margin='12px auto 0';}"
            html=html.replace(old_opening_catch,new_opening_catch)
            old_turn_catch="catch(e){visual('present','Connection interrupted. Tap Enter to continue.');hint.textContent=e.message||String(e);enter.classList.remove('hidden');started=false}"
            new_turn_catch="catch(e){const msg=e.message||String(e);visual('error',msg);hint.textContent=msg;hint.style.position='relative';hint.style.zIndex='999';hint.style.color='#181b17';hint.style.fontFamily='ui-monospace,SFMono-Regular,monospace';hint.style.fontSize='14px';hint.style.lineHeight='1.5';hint.style.padding='16px 18px';hint.style.background='#fff';hint.style.border='1px solid rgba(30,35,28,.18)';hint.style.borderRadius='12px';hint.style.maxWidth='min(92vw,760px)';hint.style.margin='12px auto 0';setTimeout(()=>{if(started){hint.removeAttribute('style');visual('listening','Connection restored. Continue.');startRecording()}},1800)}"
            html=html.replace(old_turn_catch,new_turn_catch)
            if meeting_v2_visual_patch is not None: html=meeting_v2_visual_patch.enhance(html)
            if meeting_v2_visual_refine is not None: html=meeting_v2_visual_refine.enhance(html)
            return HTMLResponse(html,headers={"Cache-Control":"no-store, no-cache, must-revalidate"})
        return response
    return HTMLResponse(f"<html><body style='font-family:system-ui;padding:32px'><h1>The Meeting is unavailable</h1><pre>{meeting_import_error}</pre></body></html>",status_code=503,headers={"Cache-Control":"no-store"})

import settings_sms_test  # noqa: F401,E402
import pilot_worker  # noqa: F401,E402
app=core.app
print("Empty Chair bootstrap loaded: "+f"version={pilot.PILOT_VERSION}, "+f"sms_live={notifications.SMS_LIVE}, "+f"email_live={notifications.EMAIL_LIVE}, "+f"resend_configured={bool(core.RESEND_API_KEY)}, "+f"google_configured={bool(google_integration.GOOGLE_CLIENT_ID)}, "+f"stripe_configured={stripe_deposits.configured()}, "+f"contact_cooldown_hours={pilot_safety.CONTACT_COOLDOWN_HOURS}")
