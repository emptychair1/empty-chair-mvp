"""Low-latency streaming layer for The Meeting.

Normal turns now return as soon as transcription + reasoning are complete. The
browser then opens a same-origin audio URL; that route proxies ElevenLabs' MP3
response as a StreamingResponse so playback can begin before the full clip has
finished generating.
"""
import json
import time
import urllib.parse
import urllib.request

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

import app as core
import meeting_v2 as meeting
import meeting_v2_runtime_fix as runtime
import m4_analysis_email


def _latest_m4_text(user, session_id):
    conn = core.connect()
    try:
        row = core.db_fetchone(
            conn,
            "SELECT text FROM meeting_v2_turns WHERE session_id=? AND user_id=? AND shop_id=? AND speaker='m4' ORDER BY created_at DESC LIMIT 1",
            (session_id, user["id"], user["shop_id"]),
        )
        return (row["text"] if row else "") or ""
    finally:
        conn.close()


def _audio_iterator(response, chunk_size=8192):
    try:
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        try:
            response.close()
        except Exception:
            pass


@core.app.get("/api/meeting-v2/audio/{session_id}")
def meeting_v2_audio_stream(request: Request, session_id: str):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    text = _latest_m4_text(user, (session_id or "").strip())
    if not text:
        return JSONResponse({"error": "No M4 response is ready for this meeting."}, status_code=404)
    if not meeting.ELEVENLABS_API_KEY:
        return JSONResponse({"error": "ELEVENLABS_API_KEY is not configured"}, status_code=503)

    voice_id = urllib.parse.quote(meeting.ELEVENLABS_VOICE_ID)
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
        "?output_format=mp3_44100_128&optimize_streaming_latency=4"
    )
    payload = {
        "text": text,
        "model_id": runtime.FAST_VOICE_MODEL,
        "voice_settings": {
            "stability": 0.34,
            "similarity_boost": 0.72,
            "style": 0.42,
            "use_speaker_boost": True,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "xi-api-key": meeting.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )
    try:
        upstream = urllib.request.urlopen(req, timeout=runtime.VOICE_TIMEOUT_SECONDS)
        return StreamingResponse(
            _audio_iterator(upstream),
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as exc:
        return JSONResponse({"error": f"M4 voice stream failed: {exc}"}, status_code=503)


# Replace the prior POST turn route with a text-first version.
core.app.router.routes[:] = [
    route for route in core.app.router.routes
    if not (
        getattr(route, "path", None) == "/api/meeting-v2/turn"
        and "POST" in (getattr(route, "methods", None) or set())
    )
]


@core.app.post("/api/meeting-v2/turn")
async def meeting_v2_turn_streaming(
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
            meeting._save_session(user, sid, state, None, answer)
            m4_analysis_email.schedule_latest_two(user)
            timings["total_ms"] = round((time.perf_counter() - started) * 1000)
            return JSONResponse({
                "ok": True,
                "session_id": sid,
                "user_text": "",
                "m4_text": answer,
                "audio_url": f"/api/meeting-v2/audio/{urllib.parse.quote(sid)}?v={time.time_ns()}",
                "state": state,
                "timings": timings,
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

        # Persist both sides after reasoning so DB I/O is no longer in the critical
        # path between transcription and the model call.
        t0 = time.perf_counter()
        meeting._save_session(user, sid, state, spoken_user, answer)
        timings["save_ms"] = round((time.perf_counter() - t0) * 1000)
        m4_analysis_email.schedule_latest_two(user)

        timings["total_ms"] = round((time.perf_counter() - started) * 1000)
        print(f"M4 meeting text-ready latency {timings}", flush=True)
        return JSONResponse({
            "ok": True,
            "session_id": sid,
            "user_text": spoken_user,
            "m4_text": answer,
            "audio_url": f"/api/meeting-v2/audio/{urllib.parse.quote(sid)}?v={time.time_ns()}",
            "state": state,
            "timings": timings,
        }, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})
    except Exception as exc:
        try:
            m4_analysis_email.schedule_latest_two(user, delay_seconds=10)
        except Exception:
            pass
        print(f"Meeting v2 streaming turn failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
