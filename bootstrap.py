"""Explicit production bootstrap for Empty Chair.

Render launches this module so additive routes and notification integrations are
always registered before the ASGI app starts serving requests.
"""

import json
import os
import urllib.error
import urllib.request
from fastapi import Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core

# Register additive pages/routes first.
import features  # noqa: F401,E402

# Install SMS/email notification overrides after core is fully imported.
import notifications  # noqa: F401,E402
import delivery_safety  # noqa: F401,E402
import stripe_deposits  # noqa: F401,E402

# Register Google authentication and the optional Calendar double-booking safety layer.
import google_integration  # noqa: F401,E402

# Guard every recovery campaign with Google Calendar free/busy when connected.
import calendar_safety  # noqa: F401,E402

# Replace the public claim endpoint with the atomic implementation after
# notification overrides are installed.
import claim_flow  # noqa: F401,E402
import booking_confirmation  # noqa: F401,E402
import booking_details  # noqa: F401,E402
import pilot_operations  # noqa: F401,E402

# Register Pilot v1.1 data structures and core Autopilot helpers.
import pilot  # noqa: F401,E402

# Apply Pilot safety rules before the canonical Fill Chairs routes are registered.
# This preserves the hard customer-contact cooldown and shop isolation.
import pilot_safety  # noqa: F401,E402

# Register the canonical Fill Chairs GET/POST flow. Page loads are database-only,
# while Calendar checks and offer delivery run after START FILLING redirects.
import fill_chairs_flow  # noqa: F401,E402

# Optional isolated live-demo account. Disabled unless explicitly enabled.
import demo_mode  # noqa: F401,E402

# Verify one-time paid activation tokens issued by the standalone sales site.
import paid_activation  # noqa: F401,E402

# Register the private platform-owner control room.
import admin_dashboard  # noqa: F401,E402

# Replace the legacy artist roster page with forward-looking utilization cards.
import artist_metrics  # noqa: F401,E402

# Register the guided first-run setup flow before the dashboard override.
import onboarding  # noqa: F401,E402

# Replace the legacy dashboard with the utilization-first owner view.
import dashboard_metrics  # noqa: F401,E402

# Register the safe, read-only M4 intelligence page.
import m4_dashboard  # noqa: F401,E402

# The Meeting is deliberately non-critical. A Meeting-specific configuration or
# provider failure must never prevent the Empty Chair core app from starting.
meeting_v2 = None
meeting_import_error = None
try:
    import meeting_v2 as _meeting_v2  # noqa: F401,E402
    meeting_v2 = _meeting_v2
    # Lock the selected M4 identity defaults while still allowing Render env overrides.
    meeting_v2.ELEVENLABS_VOICE_ID = os.getenv("M4_ELEVENLABS_VOICE_ID", "DSPOFq7nD22sXYn8JKlb")
    meeting_v2.ELEVENLABS_MODEL_ID = os.getenv("M4_ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
    # Replace only the Meeting turn handler with the corrected production-safe path.
    import meeting_v2_runtime_fix  # noqa: F401,E402
except Exception as meeting_exc:  # pragma: no cover - production safety guard
    meeting_import_error = repr(meeting_exc)
    print(f"Meeting v2 disabled: {meeting_exc}")

# The opening is fixed by design, so it should not depend on Gemini. This removes
# an unnecessary provider hop before the prospect has even spoken.
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
    answer = "I'm M4. Tell me what your shop is trying not to lose."
    try:
        state, turns = meeting_v2._load_session(user, sid)
        if not turns:
            meeting_v2._save_session(user, sid, state, None, answer)
        audio64 = meeting_v2._speak(answer)
        return JSONResponse({"ok": True, "session_id": sid, "m4_text": answer, "audio_base64": audio64}, headers={"Cache-Control": "no-store"})
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
        return JSONResponse({
            "active_voice_id": voice_id,
            "active_model_id": model_id,
            "error": "ELEVENLABS_API_KEY is not configured",
        }, status_code=503)

    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/voices/{voice_id}",
        headers={"xi-api-key": meeting_v2.ELEVENLABS_API_KEY},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return JSONResponse({
            "active_voice_id": voice_id,
            "active_model_id": model_id,
            "elevenlabs_voice_id": payload.get("voice_id"),
            "name": payload.get("name"),
            "category": payload.get("category"),
            "labels": payload.get("labels"),
            "fine_tuning": payload.get("fine_tuning"),
        }, headers={"Cache-Control": "no-store"})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return JSONResponse({
            "active_voice_id": voice_id,
            "active_model_id": model_id,
            "error": f"ElevenLabs HTTP {exc.code}",
            "detail": detail[:1000],
        }, status_code=exc.code, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({
            "active_voice_id": voice_id,
            "active_model_id": model_id,
            "error": str(exc),
        }, status_code=503, headers={"Cache-Control": "no-store"})

# Always expose the public Meeting route. If the isolated subsystem cannot import,
# show the exact failure instead of returning a misleading 404.
@core.app.get("/meet-m4", response_class=HTMLResponse)
def meet_m4_bootstrap(request: Request):
    if meeting_v2 is not None:
        response = meeting_v2.meeting_v2_page(request)
        if isinstance(response, HTMLResponse):
            html = response.body.decode("utf-8")
            old = "async function opening(){busy=true;visual('thinking','Something is already here.');let form=new FormData();form.append('session_id',sessionId);form.append('opening','1');let r=await fetch('/api/meeting-v2/turn',{method:'POST',body:form,cache:'no-store'}),j=await r.json();if(!r.ok)throw Error(j.error||'Could not enter the meeting.');if(j.audio_base64)await play64(j.audio_base64);busy=false}"
            new = "async function opening(){busy=true;visual('thinking','Something is already here.');let form=new FormData();form.append('session_id',sessionId);let r=await fetch('/api/meeting-v2/opening',{method:'POST',body:form,cache:'no-store'}),j=await r.json();if(!r.ok)throw Error(j.error||'Could not enter the meeting.');if(j.audio_base64)await play64(j.audio_base64);busy=false}"
            html = html.replace(old, new)

            # Opening failure: keep diagnostics above the chamber rather than behind blur.
            old_catch = "catch(e){started=false;enter.classList.remove('hidden');visual('present',e.message||'Microphone or voice service unavailable.')}"
            new_catch = "catch(e){started=false;visual('error',e.message||'Microphone or voice service unavailable.');enter.classList.remove('hidden');enter.style.background='transparent';enter.style.backdropFilter='none';enter.style.pointerEvents='none';enterButton.style.display='none';hint.style.position='relative';hint.style.zIndex='20';hint.style.color='#383b35';hint.style.fontFamily='ui-monospace,SFMono-Regular,monospace';hint.style.fontSize='13px';hint.style.padding='14px 18px';hint.style.background='rgba(255,255,255,.96)';hint.style.border='1px solid rgba(30,35,28,.14)';hint.style.borderRadius='12px';}"
            html = html.replace(old_catch, new_catch)

            # Turn failure: this had its own catch block and was restoring the frosted overlay.
            old_turn_catch = "catch(e){visual('present','Connection interrupted. Tap Enter to continue.');hint.textContent=e.message||String(e);enter.classList.remove('hidden');started=false}"
            new_turn_catch = "catch(e){started=false;visual('error',e.message||String(e));enter.classList.remove('hidden');enter.style.background='transparent';enter.style.backdropFilter='none';enter.style.pointerEvents='none';enterButton.style.display='none';hint.textContent=e.message||String(e);hint.style.position='relative';hint.style.zIndex='20';hint.style.color='#383b35';hint.style.fontFamily='ui-monospace,SFMono-Regular,monospace';hint.style.fontSize='13px';hint.style.lineHeight='1.45';hint.style.padding='14px 18px';hint.style.background='rgba(255,255,255,.96)';hint.style.border='1px solid rgba(30,35,28,.14)';hint.style.borderRadius='12px';hint.style.maxWidth='min(92vw,760px)';hint.style.margin='12px auto 0';}"
            html = html.replace(old_turn_catch, new_turn_catch)
            return HTMLResponse(html, headers={"Cache-Control": "no-store"})
        return response
    return HTMLResponse(
        f"<html><body style='font-family:system-ui;padding:32px'><h1>The Meeting is unavailable</h1><pre>{meeting_import_error}</pre></body></html>",
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )

# Add a safe Settings-page Twilio delivery tester.
import settings_sms_test  # noqa: F401,E402

# Continuously expires stale offers and advances active campaigns even when
# nobody has the dashboard open.
import pilot_worker  # noqa: F401,E402

app = core.app

print(
    "Empty Chair bootstrap loaded: "
    f"version={pilot.PILOT_VERSION}, "
    f"sms_live={notifications.SMS_LIVE}, "
    f"email_live={notifications.EMAIL_LIVE}, "
    f"resend_configured={bool(core.RESEND_API_KEY)}, "
    f"google_configured={bool(google_integration.GOOGLE_CLIENT_ID)}, "
    f"stripe_configured={stripe_deposits.configured()}, "
    f"contact_cooldown_hours={pilot_safety.CONTACT_COOLDOWN_HOURS}"
)
