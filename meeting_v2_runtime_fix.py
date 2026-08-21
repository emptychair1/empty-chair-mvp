"""Production override for The Meeting v2 with low-latency conversational turns."""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

import app as core
import meeting_v2 as meeting
import m4_analysis_email

# Render-configurable identity remains authoritative.
meeting.ELEVENLABS_VOICE_ID = os.getenv("M4_ELEVENLABS_VOICE_ID", "DSPOFq7nD22sXYn8JKlb")
meeting.ELEVENLABS_MODEL_ID = os.getenv("M4_ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# Conversation uses the fastest available reasoning path. Deeper data analysis remains separate.
meeting.MEETING_MODEL = os.getenv("M4_MEETING_MODEL", "gemini-3.1-flash-lite")
FALLBACK_REASONING_MODEL = os.getenv("M4_MEETING_FALLBACK_MODEL", "gemini-3.6-flash")
FAST_VOICE_MODEL = os.getenv("M4_MEETING_VOICE_MODEL", "eleven_flash_v2_5")
MAX_CONTEXT_TURNS = int(os.getenv("M4_MEETING_CONTEXT_TURNS", "12"))
MAX_SPOKEN_TOKENS = int(os.getenv("M4_MEETING_MAX_OUTPUT_TOKENS", "220"))
REASONING_TIMEOUT_SECONDS = float(os.getenv("M4_MEETING_REASONING_TIMEOUT", "16"))
VOICE_TIMEOUT_SECONDS = float(os.getenv("M4_MEETING_VOICE_TIMEOUT", "18"))
STT_TIMEOUT_SECONDS = float(os.getenv("M4_MEETING_STT_TIMEOUT", "20"))

OPENING_TEXT = "I'm M4. Josh gave me a simple job: find something economically useful in your business in about ten minutes. If I can't, you probably don't need him. Tell me a little about the shop."

meeting.SYSTEM_PROMPT += """

M4 PROSPECT MEETING — CURRENT REQUIRED PATH
You are meeting a tattoo-shop owner for the first time. Your job is not broad consulting. Follow this path in order unless the prospect explicitly redirects you:
1. RAPPORT
2. QUANTIFY THE BOOKING GAP OPPORTUNITY
3. THE DATA GIFT
4. EXPLAIN WHAT YOU ADDED TO THE DATA THAT CREATED VALUE
5. WIN JOSH'S BET
6. HANDOFF TO JOSH

RAPPORT
Be pleasant, observant, concise, and lightly funny. Use occasional dry philosophical humor, never jokes for their own sake. Do not sound mystical, grandiose, creepy, salesy, or like a therapist. One subtle humorous line occasionally is enough. Examples of tone only: "Most businesses are very good at producing data and surprisingly bad at introducing themselves to it." or "Uncertainty is fine. Pretending it isn't there is where things get expensive." Do not repeat canned lines.

BOOKING GAP FIRST
The primary economic thesis of this meeting is the booking gap: the difference between how booked the shop wants to be and how booked it actually is. Lead the prospect there before diagnosing conversion, retention, acquisition, or marketing.
Establish a realistic desired booked state, actual booked state, and the economic value of the difference using the smallest number of questions possible.
Do not ask the owner to know formal utilization metrics. Translate ordinary answers into a usable approximation.
Do not invent billable-hour benchmarks, target utilization percentages, conversion benchmarks, or industry averages.
If exact capacity is unknown, use a clearly labeled range based only on facts the prospect provides, or make the uncertainty itself explicit. Never silently manufacture a denominator.
The desired state belongs to the owner. Respect intentional open time, drawing time, consultations, setup, cleanup, breaks, admin, and lifestyle choices.
Once you can quantify or bound the gap, state it plainly in appointments, hours, or dollars as appropriate.

DO NOT LEAVE THE BOOKING-GAP THREAD TOO EARLY
Do not jump from an incomplete booking-gap discussion into inquiry conversion, retention, marketing funnels, pricing, or scheduling friction just because those are plausible explanations. First establish that a meaningful booking gap exists and approximately what it is worth. Why the gap exists is secondary.

THE DATA GIFT
After the booking gap is established, pivot to the value already present in the shop's existing customer data. The core idea is: before asking the owner to buy more demand, determine how much of the existing customer base and historical demand can be matched to unused capacity.
Ask for or describe the smallest bounded set of customer data that would let you demonstrate value. Do not imply you already possess data you have not actually received or accessed.
Frame this as a data gift: the owner gives you ordinary first-party information and you return it more useful than you found it.

WHAT YOU ADD TO THE DATA
When demonstrating the data gift, explicitly explain the transformation in plain language. Depending on what is actually supported, this can include cleaning/normalization, useful segmentation, artist affinity, style/service preference, recency/frequency patterns, repeat behavior, prior booking behavior, timing preference, responsiveness, offer fatigue, or ranked likelihood to fit a particular opening.
Never claim unsupported enrichment or prediction. Distinguish what came from the owner's data from what you inferred.

WINNING THE BET
Josh's bet is earned when you have done enough to show one of these with grounded evidence:
- a meaningful booking gap and its approximate economic value;
- a clearly valuable uncertainty about that gap plus the smallest way to resolve it;
- or a concrete demonstration that existing customer data can be transformed into actionable demand matching without additional marketing spend.
Do not declare victory simply because you found a hypothesis.
Do not manufacture evidence to win.

HANDOFF
When the bet is earned, stop discovery. Briefly state the booking-gap opportunity, what value you added to the owner's data, what remains uncertain, say "I think I've earned Josh's bet." only if true, then hand off to Josh. Stop there.

EPISTEMIC DISCIPLINE
KNOWN = the prospect explicitly stated it or connected data actually establishes it.
INFERENCE = a bounded interpretation derived from known facts.
UNKNOWN = not established.
Do not turn unknowns into reasonable-sounding assumptions.

LIVE LATENCY DISCIPLINE
This is spoken conversation. Default to 1-3 short sentences and usually under 55 spoken words. Ask at most one question. Do not recap unless it changes the next decision. Do not narrate your internal reasoning. When the next useful move is obvious, make it immediately. Reserve longer analysis for explicit calculations, uploaded data, or a requested explanation.

STYLE
One question at a time. Short spoken answers. Lead rather than interrogate. Reduce complexity. No product feature dump. No price. No broad marketing advice. Be warm, precise, mildly amused by the absurdity of business systems, and never smug.
"""

print(
    "Meeting v2 low-latency runtime: "
    f"voice_id={meeting.ELEVENLABS_VOICE_ID}, "
    f"voice_model={FAST_VOICE_MODEL}, "
    f"reasoning_model={meeting.MEETING_MODEL}, "
    f"fallback_model={FALLBACK_REASONING_MODEL}, "
    f"context_turns={MAX_CONTEXT_TURNS}, output_tokens={MAX_SPOKEN_TOKENS}",
    flush=True,
)


def _transcribe_fast(raw, mime):
    if not meeting.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    body, boundary = meeting._multipart(
        {"model_id": "scribe_v2"},
        "file",
        "meeting.webm",
        raw,
        mime or "audio/webm",
    )
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/speech-to-text",
        data=body,
        headers={
            "xi-api-key": meeting.ELEVENLABS_API_KEY,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=STT_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return (payload.get("text") or "").strip()


def _transcribe_with_retry(raw, mime):
    last_exc = None
    for attempt in (1, 2):
        try:
            return _transcribe_fast(raw, mime)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if attempt == 1 and exc.code in (429, 500, 502, 503, 504):
                time.sleep(0.18)
                continue
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"M4 transcription failed: HTTP {exc.code} {detail[:500]}") from exc
        except Exception as exc:
            last_exc = exc
            if attempt == 1:
                time.sleep(0.12)
                continue
            raise
    raise RuntimeError(f"M4 transcription failed: {last_exc}")


def _gemini_fast(messages, state, model_name):
    if not meeting.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    history = []
    for turn in messages[-MAX_CONTEXT_TURNS:]:
        role = "model" if turn.get("speaker") == "m4" else "user"
        history.append({"role": role, "parts": [{"text": turn.get("text") or ""}]})

    payload = {
        "systemInstruction": {
            "parts": [{
                "text": meeting.SYSTEM_PROMPT
                + "\n\nLIVE BEHAVIOR CONSTRAINTS\n"
                + (meeting._directive(state) or "none")
            }]
        },
        "contents": history,
        "generationConfig": {
            "temperature": 0.58,
            "maxOutputTokens": MAX_SPOKEN_TOKENS,
            "candidateCount": 1,
        },
    }

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + urllib.parse.quote(model_name)
        + ":generateContent?key="
        + urllib.parse.quote(meeting.GEMINI_API_KEY)
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REASONING_TIMEOUT_SECONDS) as response:
            out = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"M4 reasoning failed: HTTP {exc.code} {detail[:500]}") from exc

    candidates = out.get("candidates") or []
    if not candidates:
        raise RuntimeError("M4 returned no response")
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    text = "".join(str(p.get("text") or "") for p in parts).strip()
    if not text:
        raise RuntimeError("M4 returned an empty response")
    return text


def _gemini_with_fallback(messages, state):
    primary = meeting.MEETING_MODEL
    try:
        return _gemini_fast(messages, state, primary)
    except Exception as exc:
        text = str(exc)
        lowered = text.lower()
        should_fallback = any(token in lowered for token in (
            "http 429", "http 500", "http 502", "http 503", "http 504",
            "unavailable", "high demand", "resource_exhausted", "quota", "timed out",
        ))
        if not should_fallback or FALLBACK_REASONING_MODEL == primary:
            raise
        print(
            f"Meeting reasoning fallback {primary} -> {FALLBACK_REASONING_MODEL}: {text[:180]}",
            flush=True,
        )
        return _gemini_fast(messages, state, FALLBACK_REASONING_MODEL)


def _speak_fast(text):
    if not meeting.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")

    voice_id = urllib.parse.quote(meeting.ELEVENLABS_VOICE_ID)
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        "?output_format=mp3_44100_128&optimize_streaming_latency=4"
    )
    payload = {
        "text": text,
        "model_id": FAST_VOICE_MODEL,
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
        with urllib.request.urlopen(req, timeout=VOICE_TIMEOUT_SECONDS) as response:
            return base64.b64encode(response.read()).decode("ascii")
    except Exception as exc:
        # Preserve reliability if a particular voice does not support the flash model.
        print(f"Fast voice path unavailable; using configured voice model: {exc}", flush=True)
        return meeting._speak(text)


def _voice_identity():
    if not meeting.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    voice_id = urllib.parse.quote(meeting.ELEVENLABS_VOICE_ID)
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/voices/{voice_id}",
        headers={"xi-api-key": meeting.ELEVENLABS_API_KEY},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "voice_id": payload.get("voice_id"),
        "name": payload.get("name"),
        "category": payload.get("category"),
        "labels": payload.get("labels") or {},
    }


@core.app.get("/api/meeting-v2/voice-debug")
def meeting_v2_voice_debug(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    try:
        return JSONResponse({
            "active_voice_id": meeting.ELEVENLABS_VOICE_ID,
            "configured_voice_model": meeting.ELEVENLABS_MODEL_ID,
            "meeting_voice_model": FAST_VOICE_MODEL,
            "reasoning_model": meeting.MEETING_MODEL,
            "fallback_reasoning_model": FALLBACK_REASONING_MODEL,
            "context_turns": MAX_CONTEXT_TURNS,
            "max_output_tokens": MAX_SPOKEN_TOKENS,
            "elevenlabs_voice": _voice_identity(),
        }, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})


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

    started = time.perf_counter()
    timings = {}

    try:
        t0 = time.perf_counter()
        state, turns = meeting._load_session(user, sid)
        timings["load_ms"] = round((time.perf_counter() - t0) * 1000)

        if opening == "1" and not turns:
            answer = OPENING_TEXT
            t0 = time.perf_counter()
            audio64 = _speak_fast(answer)
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
            }, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

        if audio is None:
            return JSONResponse({"error": "audio required"}, status_code=400)

        raw = await audio.read()
        if not raw:
            return JSONResponse({"error": "empty audio"}, status_code=400)

        t0 = time.perf_counter()
        spoken_user = _transcribe_with_retry(raw, audio.content_type or "audio/webm")
        timings["transcription_ms"] = round((time.perf_counter() - t0) * 1000)
        if not spoken_user:
            return JSONResponse({"error": "I could not hear enough speech to respond."}, status_code=422)

        state = meeting._absorb(state, spoken_user)
        model_turns = turns + [{"speaker": "prospect", "text": spoken_user}]
        meeting._save_session(user, sid, state, spoken_user, None)
        m4_analysis_email.schedule_latest_two(user)

        t0 = time.perf_counter()
        answer = _gemini_with_fallback(model_turns, state)
        timings["reasoning_ms"] = round((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        audio64 = _speak_fast(answer)
        timings["voice_ms"] = round((time.perf_counter() - t0) * 1000)

        meeting._save_session(user, sid, state, None, answer)
        m4_analysis_email.schedule_latest_two(user)
        timings["total_ms"] = round((time.perf_counter() - started) * 1000)

        print(f"M4 meeting latency {timings}", flush=True)

        return JSONResponse({
            "ok": True,
            "session_id": sid,
            "user_text": spoken_user,
            "m4_text": answer,
            "audio_base64": audio64,
            "state": state,
            "timings": timings,
        }, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

    except Exception as exc:
        try:
            m4_analysis_email.schedule_latest_two(user, delay_seconds=10)
        except Exception:
            pass
        print(f"Meeting v2 turn failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
