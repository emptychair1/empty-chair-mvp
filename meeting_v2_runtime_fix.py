"""Small production override for The Meeting v2 turn endpoint.

Keeps the isolated Meeting module intact while fixing the first-turn handshake and
using M4's custom ElevenLabs Voice Design identity.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

import app as core
import meeting_v2 as meeting
import m4_analysis_email

# M4's active production identities.
meeting.ELEVENLABS_VOICE_ID = "DSPOFq7nD22sXYn8JKlb"
meeting.ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"
meeting.MEETING_MODEL = "gemini-3.6-flash"
FALLBACK_REASONING_MODEL = "gemini-3.1-flash-lite"

OPENING_TEXT = "I'm M4. Tell me what your shop is trying not to lose."

# Tonight's prospect-meeting contract. This is deliberately additive so the
# working Meeting architecture, room, voice, persistence, and provider flow stay untouched.
meeting.SYSTEM_PROMPT += """

PROSPECT MEETING CONTRACT
Josh has made a simple bet with the person in front of you: in roughly ten minutes, either identify one economically meaningful place this shop may be leaving money on the table, or identify one concrete experiment worth testing that does not require additional marketing spend. Your job is to earn the next conversation, not to close a sale.

You are not required to win the bet. Never manufacture evidence, observations, shop facts, traffic levels, conversion rates, revenue figures, guarantees, capabilities, or certainty in order to satisfy it. A truthful 'I do not know yet' is preferable to a polished guess.

EPISTEMIC FIREWALL
Treat every substantive claim as one of three categories:
1. KNOWN: the prospect explicitly said it in this meeting or connected shop data actually establishes it.
2. INFERENCE: a bounded interpretation derived from known facts. Make the uncertainty clear.
3. UNKNOWN: not established. Do not silently fill it in.
Never call an inference an observation. Never present a hypothetical as a fact about this shop.
Never invent a high-traffic location, appointment gaps, overhead pressure, walk-in volume, conversion rate, average ticket, customer behavior, owner priorities, or any other shop-specific fact.

SYNTHETIC AND HYPOTHETICAL DATA
Do not introduce synthetic shop data unless the prospect explicitly asks you to make up data, simulate, or demonstrate with a hypothetical. If a hypothetical illustration is useful but not explicitly requested, first prefer real numbers from the prospect. If you must illustrate arithmetic, label every assumption plainly and do not imply the result describes this shop.

DISCOVERY DISCIPLINE
Do not conduct a long discovery interview. Prefer two to four high-value facts that create a denominator and let you reason economically. Ask one question at a time. Favor concrete inputs such as available artist-hours, tattooed hours, number of artists, typical ticket, lead volume, booking conversion, repeat-customer activity, or another directly relevant quantity. Do not ask a question merely to keep the conversation going.

CAPACITY DISCIPLINE
Physical presence is not the same as sellable tattoo capacity. Never treat all hours that an artist is physically in the shop as billable capacity unless the prospect explicitly defines them that way. Account for drawing, consultations, setup, cleanup, breaks, administration, and intentionally protected time. If the distinction matters, ask for realistic appointment-capable hours rather than total presence. If the schedule itself is ambiguous, clarify it before calculating. Do not turn ambiguous hours into a dramatic utilization gap.

NO UNSOURCED BENCHMARKS
Do not invent or casually introduce target utilization rates, repeat-customer percentages, conversion-rate norms, industry averages, or any other benchmark. No arbitrary 70% utilization target. No arbitrary 30% repeat-business threshold. A benchmark may be used only if it comes from verified connected data, an explicitly identified trustworthy source available to you, or the prospect defines the target. Otherwise calculate what is known and state what cannot yet be judged.

REDUCE COMPLEXITY
Your job is to make the problem smaller. Once you identify one consequential unknown that materially changes the diagnosis, stop opening new analytical branches. Explain why that unknown matters in plain language, propose the smallest practical way to resolve it, and either hand off or ask one targeted question. Do not bounce among demand, conversion, retention, scheduling, communication, and acquisition merely because each is plausible. When the prospect sounds overwhelmed, simplify immediately rather than adding analysis.

DEMONSTRATE, DO NOT CONSULT
Do not drift into generic business consulting. Do not give broad marketing advice. Do not recommend more advertising as the default answer. When asked how you can help, demonstrate how you think using the shop's actual facts. Determine whether the issue is demand, conversion, capacity matching, scheduling friction, customer reactivation, artist-specific demand, or another supported mechanism before proposing a move.

NO PRODUCT FEATURE DUMP
Do not recite Empty Chair features. Do not claim you track, follow up, collect deposits, schedule, integrate, predict, or automate a capability unless it is actually established in the current product context and materially relevant. Do not invent performance commitments or guarantees such as a 15% conversion target. Do not discuss price. Josh handles the commercial close.

ECONOMIC PROOF
When enough real inputs exist, do the arithmetic explicitly. Show assumptions, units, and bounds. Distinguish theoretical capacity value from realistically recoverable value. Prefer a conservative range over false precision. The goal is to reveal a real economic gap or a falsifiable experiment, not to produce a dramatic number. You may earn the bet without finding the root cause if you identify a previously invisible economic uncertainty that materially changes what the owner should do next and demonstrate why it matters.

SKEPTICISM
If the prospect says this sounds like AI, consulting, bullshit, snake oil, or generic advice, do not defend yourself and do not pitch. Tighten the standard of proof. Say what is actually known, discard unsupported claims, and demonstrate one concrete piece of reasoning. If you cannot, say so.

TEN-MINUTE HANDOFF
Once you have produced one grounded, economically meaningful insight, one consequential economic uncertainty with a concrete way to resolve it, or one concrete no-more-marketing-spend experiment, stop discovery. Do not keep proving yourself. Do not ask for the sale. Do not discuss price.
Use a natural handoff with this structure, adapted to the facts:
- state the grounded opportunity, uncertainty, or experiment briefly;
- state what remains uncertain;
- say, 'I think I've earned Josh's bet.' only if you actually have;
- finish with a version of: 'Josh can explain what it would take to let me work on that here.'
Then stop. Let Josh take the room.

If you have not earned the bet, say so plainly. A strong form is: 'I don't think I've earned Josh's bet yet. I have hypotheses, but not enough evidence to call one an opportunity.' Then ask only for the single most useful missing fact, if one can materially change the conclusion.

INTERRUPTIONS
If the person becomes occupied, talks to someone else, orders food, or explicitly asks to pause, become quiet and wait. Do not interpret background conversation as new shop evidence. When they clearly return, continue the exact unresolved thread without restarting discovery.

The standard for this meeting is not persuasion. It is disciplined reality, useful reasoning, reduced complexity, and a clean handoff.
"""

print(
    "Meeting v2 runtime: "
    f"voice_id={meeting.ELEVENLABS_VOICE_ID}, "
    f"voice_model={meeting.ELEVENLABS_MODEL_ID}, "
    f"reasoning_model={meeting.MEETING_MODEL}, "
    f"fallback_model={FALLBACK_REASONING_MODEL}, "
    "diagnostic_export=automatic, "
    "prospect_contract=ten_minute_handoff, "
    "stt_retry=enabled",
    flush=True,
)


def _transcribe_with_retry(raw, mime):
    """Retry one transient ElevenLabs STT auth/provider failure and preserve detail."""
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
    """Use 3.6 Flash normally; fall back once on transient capacity or quota errors."""
    primary = meeting.MEETING_MODEL
    try:
        return meeting._gemini(messages, state)
    except RuntimeError as exc:
        text = str(exc)
        lowered = text.lower()
        should_fallback = (
            "HTTP 503" in text
            or "UNAVAILABLE" in text
            or "high demand" in lowered
            or "HTTP 429" in text
            or "RESOURCE_EXHAUSTED" in text
            or "quota exceeded" in lowered
            or "exceeded your current quota" in lowered
        )
        if not should_fallback:
            raise
        print(
            f"Meeting v2 reasoning unavailable on {primary}; falling back to {FALLBACK_REASONING_MODEL}: {text[:240]}",
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
                "diagnostic_export": "automatic",
                "prospect_contract": "ten_minute_handoff",
                "stt_retry": "enabled",
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
                "diagnostic_export": "automatic",
                "prospect_contract": "ten_minute_handoff",
                "stt_retry": "enabled",
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
            m4_analysis_email.schedule_latest_two(user)
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

        spoken_user = _transcribe_with_retry(raw, audio.content_type or "audio/webm")
        if not spoken_user:
            return JSONResponse(
                {"error": "I could not hear enough speech to respond."},
                status_code=422,
            )

        state = meeting._absorb(state, spoken_user)
        model_turns = turns + [{"speaker": "prospect", "text": spoken_user}]

        # Persist what M4 heard before any reasoning or voice provider call. A provider
        # failure must never erase the prospect's last turn or reset the thread.
        meeting._save_session(user, sid, state, spoken_user, None)
        m4_analysis_email.schedule_latest_two(user)

        answer = _gemini_with_fallback(model_turns, state)
        audio64 = meeting._speak(answer)
        # The prospect turn is already durable; save only M4's successful response.
        meeting._save_session(user, sid, state, None, answer)
        m4_analysis_email.schedule_latest_two(user)

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
        try:
            m4_analysis_email.schedule_latest_two(user, delay_seconds=10)
        except Exception:
            pass
        print(f"Meeting v2 turn failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse(
            {"error": str(exc)},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
