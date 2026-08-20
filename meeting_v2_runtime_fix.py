"""Small production override for The Meeting v2 turn endpoint.

Keeps the isolated Meeting module intact while fixing the first-turn handshake and
using a known API-compatible ElevenLabs test voice while we validate the full loop.
"""
from fastapi import File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

import app as core
import meeting_v2 as meeting

# Temporary known API-compatible ElevenLabs test voice.
# Once the full Meeting loop is verified, swap this back to M4's custom voice.
meeting.ELEVENLABS_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
meeting.ELEVENLABS_MODEL_ID = "eleven_flash_v2_5"

OPENING_TEXT = "I'm M4. Tell me what your shop is trying not to lose."

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

        # The opening is deterministic. Do not involve Gemini before the prospect
        # has said anything; just speak M4's fixed first line through ElevenLabs.
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
        answer = meeting._gemini(model_turns, state)
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
        return JSONResponse(
            {"error": str(exc)},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
