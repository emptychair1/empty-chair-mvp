"""Reliable low-latency Meeting turn override.

The experimental browser audio-stream path proved unreliable in production.
This keeps the fast STT/reasoning path but returns a complete fast-voice clip in
the turn response so the client always has something it can play.
"""
import time

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

import app as core
import meeting_v2 as meeting
import meeting_v2_runtime_fix as runtime
import m4_analysis_email


core.app.router.routes[:] = [
    route for route in core.app.router.routes
    if not (
        getattr(route, "path", None) == "/api/meeting-v2/turn"
        and "POST" in (getattr(route, "methods", None) or set())
    )
]


@core.app.post("/api/meeting-v2/turn")
async def meeting_v2_turn_reliable(
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

    started = time.perf_counter()
    timings = {}

    try:
        t0 = time.perf_counter()
        state, turns = meeting._load_session(user, sid)
        timings["load_ms"] = round((time.perf_counter() - t0) * 1000)

        if opening == "1" and not turns:
            answer = runtime.OPENING_TEXT
            t0 = time.perf_counter()
            audio64 = runtime._speak_fast(answer)
            timings["voice_ms"] = round((time.perf_counter() - t0) * 1000)
            meeting._save_session(user, sid, state, None, answer)
            m4_analysis_email.schedule_latest_two(user)
            timings["total_ms"] = round((time.perf_counter() - started) * 1000)
            return JSONResponse({
                "ok": True,
                "session_id": sid,
                "user_text": "",
                "m4_text": answer,
                "audio_base64": audio64,
                "state": state,
                "timings": timings,
                "audio_mode": "reliable_fast_clip",
            }, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

        if audio is None:
            return JSONResponse({"error": "audio required"}, status_code=400)

        raw = await audio.read()
        if not raw:
            return JSONResponse({"error": "empty audio"}, status_code=400)

        t0 = time.perf_counter()
        spoken_user = runtime._transcribe_with_retry(raw, audio.content_type or "audio/webm")
        timings["transcription_ms"] = round((time.perf_counter() - t0) * 1000)
        if not spoken_user:
            return JSONResponse({"error": "I could not hear enough speech to respond."}, status_code=422)

        state = meeting._absorb(state, spoken_user)
        model_turns = turns + [{"speaker": "prospect", "text": spoken_user}]

        t0 = time.perf_counter()
        answer = runtime._gemini_with_fallback(model_turns, state)
        timings["reasoning_ms"] = round((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        audio64 = runtime._speak_fast(answer)
        timings["voice_ms"] = round((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        meeting._save_session(user, sid, state, spoken_user, answer)
        timings["save_ms"] = round((time.perf_counter() - t0) * 1000)
        m4_analysis_email.schedule_latest_two(user)

        timings["total_ms"] = round((time.perf_counter() - started) * 1000)
        print(f"M4 meeting reliable latency {timings}", flush=True)

        return JSONResponse({
            "ok": True,
            "session_id": sid,
            "user_text": spoken_user,
            "m4_text": answer,
            "audio_base64": audio64,
            "state": state,
            "timings": timings,
            "audio_mode": "reliable_fast_clip",
        }, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

    except Exception as exc:
        try:
            m4_analysis_email.schedule_latest_two(user, delay_seconds=10)
        except Exception:
            pass
        print(f"Meeting reliable turn failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
