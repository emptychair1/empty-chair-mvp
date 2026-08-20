"""Guest-session access for the prospect-facing M4 Meeting.

A visitor must first enter through /meet-m4, which marks the existing signed
session cookie as a Meeting guest. Admin and diagnostic routes are unaffected.
"""
from fastapi import File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

import app as core
import meeting_v2 as meeting
import meeting_v2_runtime_fix as runtime

GUEST_USER = {"id": "m4-meeting-guest", "shop_id": "m4-prospect-room"}


def meeting_user(request: Request):
    user = core.get_current_user(request)
    if user:
        return user
    if request.session.get("m4_meeting_guest") is True:
        return GUEST_USER.copy()
    return None


core.app.router.routes[:] = [
    route for route in core.app.router.routes
    if not (
        getattr(route, "path", None) == "/api/meeting-v2/turn"
        and "POST" in (getattr(route, "methods", None) or set())
    )
]


@core.app.post("/api/meeting-v2/turn")
async def meeting_v2_turn_guest(
    request: Request,
    session_id: str = Form(...),
    opening: str = Form("0"),
    audio: UploadFile | None = File(None),
):
    user = meeting_user(request)
    if not user:
        return JSONResponse({"error": "Enter the Meeting first."}, status_code=401)

    sid = (session_id or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)

    try:
        state, turns = meeting._load_session(user, sid)
        if opening == "1" and not turns:
            answer = runtime.OPENING_TEXT
            audio64 = meeting._speak(answer)
            meeting._save_session(user, sid, state, None, answer)
            return JSONResponse({"ok": True, "session_id": sid, "user_text": "", "m4_text": answer, "audio_base64": audio64, "state": state}, headers={"Cache-Control": "no-store"})

        if audio is None:
            return JSONResponse({"error": "audio required"}, status_code=400)
        raw = await audio.read()
        if not raw:
            return JSONResponse({"error": "empty audio"}, status_code=400)

        spoken_user = meeting._transcribe(raw, audio.content_type or "audio/webm")
        if not spoken_user:
            return JSONResponse({"error": "I could not hear enough speech to respond."}, status_code=422)

        state = meeting._absorb(state, spoken_user)
        model_turns = turns + [{"speaker": "prospect", "text": spoken_user}]
        meeting._save_session(user, sid, state, spoken_user, None)
        answer = runtime._gemini_with_fallback(model_turns, state)
        audio64 = meeting._speak(answer)
        meeting._save_session(user, sid, state, None, answer)
        return JSONResponse({"ok": True, "session_id": sid, "user_text": spoken_user, "m4_text": answer, "audio_base64": audio64, "state": state}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        print(f"Meeting guest turn failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
