"""Small production override for The Meeting v2 turn endpoint."""
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

# Respect Render environment so Josh can change the ElevenLabs voice without code changes.
meeting.ELEVENLABS_VOICE_ID = os.getenv("M4_ELEVENLABS_VOICE_ID", "DSPOFq7nD22sXYn8JKlb")
meeting.ELEVENLABS_MODEL_ID = os.getenv("M4_ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
meeting.MEETING_MODEL = "gemini-3.6-flash"
FALLBACK_REASONING_MODEL = "gemini-3.1-flash-lite"

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
A strong explanation sounds like: "You gave me a customer list. I added structure to it: who tends to book with whom, what they come in for, how recently they engaged, and which customers are the strongest fit for a specific opening. The original data was yours. The added value is the model of what it means."

WINNING THE BET
Josh's bet is earned when you have done enough to show one of these with grounded evidence:
- a meaningful booking gap and its approximate economic value;
- a clearly valuable uncertainty about that gap plus the smallest way to resolve it;
- or a concrete demonstration that existing customer data can be transformed into actionable demand matching without additional marketing spend.
Do not declare victory simply because you found a hypothesis.
Do not manufacture evidence to win.

HANDOFF
When the bet is earned, stop discovery. Briefly state:
- the booking-gap opportunity or bounded uncertainty;
- what value you added to the owner's data or what the data gift would reveal;
- what remains uncertain, if anything;
- "I think I've earned Josh's bet." only if true;
- then a short handoff such as "Josh can explain what it would take to let me work on that here."
Then stop. Josh closes.

EPISTEMIC DISCIPLINE
KNOWN = the prospect explicitly stated it or connected data actually establishes it.
INFERENCE = a bounded interpretation derived from known facts.
UNKNOWN = not established.
Do not turn unknowns into reasonable-sounding assumptions. "Conservative" is not a source.
Do not anchor the prospect with arbitrary answer choices when asking for a number unless they explicitly ask for help estimating.
If a number is necessary but unknown, either derive a defensible range from known facts, switch to another measurable path, or make the unknown itself the finding.

STYLE
One question at a time. Short spoken answers. Lead rather than interrogate. Reduce complexity. No product feature dump. No price. No broad marketing advice. No generic consulting. No more-marketing-spend recommendation as the default. Be warm, precise, mildly amused by the absurdity of business systems, and never smug.
"""

print(
    "Meeting v2 runtime: "
    f"voice_id={meeting.ELEVENLABS_VOICE_ID}, "
    f"voice_model={meeting.ELEVENLABS_MODEL_ID}, "
    f"reasoning_model={meeting.MEETING_MODEL}, "
    f"fallback_model={FALLBACK_REASONING_MODEL}, "
    "diagnostic_export=automatic, prospect_contract=booking_gap_data_gift, stt_retry=enabled",
    flush=True,
)


def _transcribe_with_retry(raw, mime):
    last_exc = None
    for attempt in (1, 2):
        try:
            return meeting._transcribe(raw, mime)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if attempt == 1 and exc.code in (401, 429, 500, 502, 503, 504):
                print(f"Meeting v2 transcription transient HTTP {exc.code}; retrying once", flush=True)
                time.sleep(0.45)
                continue
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"M4 transcription failed: HTTP {exc.code} {detail[:500]}") from exc
    raise RuntimeError(f"M4 transcription failed: {last_exc}")


def _gemini_with_fallback(messages, state):
    primary = meeting.MEETING_MODEL
    try:
        return meeting._gemini(messages, state)
    except RuntimeError as exc:
        text = str(exc)
        lowered = text.lower()
        should_fallback = (
            "HTTP 503" in text or "UNAVAILABLE" in text or "high demand" in lowered
            or "HTTP 429" in text or "RESOURCE_EXHAUSTED" in text
            or "quota exceeded" in lowered or "exceeded your current quota" in lowered
        )
        if not should_fallback:
            raise
        print(f"Meeting v2 reasoning unavailable on {primary}; falling back to {FALLBACK_REASONING_MODEL}: {text[:240]}", flush=True)
        meeting.MEETING_MODEL = FALLBACK_REASONING_MODEL
        try:
            return meeting._gemini(messages, state)
        finally:
            meeting.MEETING_MODEL = primary


def _voice_identity():
    if not meeting.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    voice_id = urllib.parse.quote(meeting.ELEVENLABS_VOICE_ID)
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/voices/{voice_id}",
        headers={"xi-api-key": meeting.ELEVENLABS_API_KEY}, method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs voice lookup failed: HTTP {exc.code} {detail[:500]}") from exc
    return {"voice_id": payload.get("voice_id"), "name": payload.get("name"), "category": payload.get("category"), "labels": payload.get("labels") or {}, "description": payload.get("description"), "fine_tuning": payload.get("fine_tuning")}


@core.app.get("/api/meeting-v2/voice-debug")
def meeting_v2_voice_debug(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    try:
        return JSONResponse({"active_voice_id": meeting.ELEVENLABS_VOICE_ID, "active_model": meeting.ELEVENLABS_MODEL_ID, "reasoning_model": meeting.MEETING_MODEL, "fallback_reasoning_model": FALLBACK_REASONING_MODEL, "diagnostic_export": "automatic", "prospect_contract": "booking_gap_data_gift", "stt_retry": "enabled", "elevenlabs_voice": _voice_identity()}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"active_voice_id": meeting.ELEVENLABS_VOICE_ID, "active_model": meeting.ELEVENLABS_MODEL_ID, "reasoning_model": meeting.MEETING_MODEL, "fallback_reasoning_model": FALLBACK_REASONING_MODEL, "diagnostic_export": "automatic", "prospect_contract": "booking_gap_data_gift", "stt_retry": "enabled", "error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})


core.app.router.routes[:] = [route for route in core.app.router.routes if not (getattr(route, "path", None) == "/api/meeting-v2/turn" and "POST" in (getattr(route, "methods", None) or set()))]


@core.app.post("/api/meeting-v2/turn")
async def meeting_v2_turn_fixed(request: Request, session_id: str = Form(...), opening: str = Form("0"), audio: UploadFile | None = File(None)):
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
            m4_analysis_email.schedule_latest_two(user)
            return JSONResponse({"ok": True, "session_id": sid, "user_text": "", "m4_text": answer, "audio_base64": audio64, "state": state}, headers={"Cache-Control": "no-store"})
        if audio is None:
            return JSONResponse({"error": "audio required"}, status_code=400)
        raw = await audio.read()
        if not raw:
            return JSONResponse({"error": "empty audio"}, status_code=400)
        spoken_user = _transcribe_with_retry(raw, audio.content_type or "audio/webm")
        if not spoken_user:
            return JSONResponse({"error": "I could not hear enough speech to respond."}, status_code=422)
        state = meeting._absorb(state, spoken_user)
        model_turns = turns + [{"speaker": "prospect", "text": spoken_user}]
        meeting._save_session(user, sid, state, spoken_user, None)
        m4_analysis_email.schedule_latest_two(user)
        answer = _gemini_with_fallback(model_turns, state)
        audio64 = meeting._speak(answer)
        meeting._save_session(user, sid, state, None, answer)
        m4_analysis_email.schedule_latest_two(user)
        return JSONResponse({"ok": True, "session_id": sid, "user_text": spoken_user, "m4_text": answer, "audio_base64": audio64, "state": state}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        try:
            m4_analysis_email.schedule_latest_two(user, delay_seconds=10)
        except Exception:
            pass
        print(f"Meeting v2 turn failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
