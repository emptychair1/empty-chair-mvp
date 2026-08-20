"""Small production override for The Meeting v2 turn endpoint.

Keeps the isolated Meeting module intact while fixing the first-turn handshake and
using M4's custom ElevenLabs Voice Design identity.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

import app as core
import meeting_v2 as meeting

# M4's active production identities.
meeting.ELEVENLABS_VOICE_ID = "DSPOFq7nD22sXYn8JKlb"
meeting.ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"
meeting.MEETING_MODEL = "gemini-3.6-flash"
FALLBACK_REASONING_MODEL = "gemini-3.1-flash-lite"

OPENING_TEXT = "I'm M4. Tell me what your shop is trying not to lose."

print(
    "Meeting v2 runtime: "
    f"voice_id={meeting.ELEVENLABS_VOICE_ID}, "
    f"voice_model={meeting.ELEVENLABS_MODEL_ID}, "
    f"reasoning_model={meeting.MEETING_MODEL}, "
    f"fallback_model={FALLBACK_REASONING_MODEL}",
    flush=True,
)


def _gemini_with_fallback(messages, state):
    """Use 3.6 Flash normally; fall back once when Google returns capacity 503."""
    primary = meeting.MEETING_MODEL
    try:
        return meeting._gemini(messages, state)
    except RuntimeError as exc:
        text = str(exc)
        if "HTTP 503" not in text and "UNAVAILABLE" not in text and "high demand" not in text.lower():
            raise
        print(
            f"Meeting v2 reasoning overload on {primary}; falling back to {FALLBACK_REASONING_MODEL}",
            flush=True,
        )
        meeting.MEETING_MODEL = FALLBACK_REASONING_MODEL
        try:
            return meeting._gemini(messages, state)
        finally:
            meeting.MEETING_MODEL = primary


def _voice_identity():
    """Return non-secret ElevenLabs metadata for the active voice."""
    if not meeting.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    voice_id = urllib.parse.quote(meeting.ELEVENLABS_VOICE_ID)
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/voices/{voice_id}",
        headers={"xi-api-key": meeting.ELEVENLABS_API_KEY},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs voice lookup failed: HTTP {exc.code} {detail[:500]}") from exc

    return {
        "voice_id": payload.get("voice_id"),
        "name": payload.get("name"),
        "category": payload.get("category"),
        "labels": payload.get("labels") or {},
        "description": payload.get("description"),
        "fine_tuning": payload.get("fine_tuning"),
    }


@core.app.get("/api/meeting-v2/voice-debug")
def meeting_v2_voice_debug(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    try:
        return JSONResponse(
            {
                "active_voice_id": meeting.ELEVENLABS_VOICE_ID,
                "active_model": meeting.ELEVENLABS_MODEL_ID,
                "reasoning_model": meeting.MEETING_MODEL,
                "fallback_reasoning_model": FALLBACK_REASONING_MODEL,
                "elevenlabs_voice": _voice_identity(),
            },
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return JSONResponse(
            {
                "active_voice_id": meeting.ELEVENLABS_VOICE_ID,
                "active_model": meeting.ELEVENLABS_MODEL_ID,
                "reasoning_model": meeting.MEETING_MODEL,
                "fallback_reasoning_model": FALLBACK_REASONING_MODEL,
                "error": str(exc),
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )


# Remove the original handler so FastAPI cannot select it before this corrected one.
core.app.router.routes[:] = [
    route for route in core.app.router.routes
    if not (
        getattr(route, "path", None) == "/api/meeting-v2/turn"
        and "POST" in (getattr(route, "methods", None) or set())
    )
]


@core.app.post("/api/meeting-v2/turn")
async def meeting_v2_turn_fixed(
    request: Request,
    session_id: str = Form(...),
    opening: str = Form("0"),
    audio: UploadFile | None = File(None),
):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)

    sid = (session_id or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)

    try:
        state, turns = meeting._load_session(user, sid)

        if opening == "1" and not turns:
            answer = OPENING_TEXT
            audio64 = meeting._speak(answer)
            meeting._save_session(user, sid, state, None, answer)
            return JSONResponse(
                {
                    "ok": True,
                    "session_id": sid,
                    "user_text": "",
                    "m4_text": answer,
                    "audio_base64": audio64,
                    "state": state,
                },
                headers={"Cache-Control": "no-store"},
            )

        if audio is None:
            return JSONResponse({"error": "audio required"}, status_code=400)

        raw = await audio.read()
        if not raw:
            return JSONResponse({"error": "empty audio"}, status_code=400)

        spoken_user = meeting._transcribe(raw, audio.content_type or "audio/webm")
        if not spoken_user:
            return JSONResponse(
                {"error": "I could not hear enough speech to respond."},
                status_code=422,
            )

        state = meeting._absorb(state, spoken_user)
        model_turns = turns + [{"speaker": "prospect", "text": spoken_user}]
        answer = _gemini_with_fallback(model_turns, state)
        audio64 = meeting._speak(answer)
        meeting._save_session(user, sid, state, spoken_user, answer)

        return JSONResponse(
            {
                "ok": True,
                "session_id": sid,
                "user_text": spoken_user,
                "m4_text": answer,
                "audio_base64": audio64,
                "state": state,
            },
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        print(f"Meeting v2 turn failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse(
            {"error": str(exc)},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
