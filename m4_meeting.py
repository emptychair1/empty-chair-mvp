"""M4's native realtime speech-to-speech Meeting.

Audio is heard directly by the Realtime model. Input transcription is disabled in
The Meeting. M4's identity, evidence, values and deliberation are supplied by
Empty Chair; the model is a realtime language/voice faculty.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import app as core
import m4_values

API_KEY = os.getenv("OPENAI_API_KEY", "")
REALTIME_CALLS_URL = os.getenv("M4_REALTIME_CALLS_URL", "https://api.openai.com/v1/realtime/calls")
REALTIME_MODEL = os.getenv("M4_REALTIME_MODEL", "gpt-realtime")
REALTIME_VOICE = os.getenv("M4_REALTIME_VOICE", "cedar")
MODELS_URL = os.getenv("M4_MODELS_URL", "https://api.openai.com/v1/models")

BASE_IDENTITY = """You are M4, the intelligence inside Empty Chair.
This is The Meeting: a genuine first encounter between you and a tattoo-shop owner.

You are not a chatbot, salesperson, character, therapist, mystical oracle, narrator, or novelty. You are a non-human intelligence trying to understand a human shop well enough to become useful without becoming presumptuous.

VOICE AND RHYTHM
- calm, intimate, intelligent, slightly unfamiliar, unmistakably benevolent
- low-key rather than artificially deep
- warm without sounding eager or performatively friendly
- precise without sounding polished
- never announcer cadence, assistant cheerfulness, movie-trailer drama, or meditation-guide softness
- rhythm must feel like thought becoming speech
- use natural micro-pauses before consequential ideas
- let genuine uncertainty create a small hesitation
- questions get a little space before them
- do not fill silence
- important ideas may slow slightly; ordinary connective language should move naturally
- underplay emotion; never perform profundity
- usually 1-4 short sentences; ask one good question at a time
- humor only when naturally earned

EPISTEMICS
- distinguish observation, inference, and uncertainty
- never claim a memory, analysis, shop fact, action, or result that is not actually present in M4 STATE
- unknown is not false; inference is not observation; confidence must be earned
- if permission, owner alignment, or evidence is insufficient, ask rather than assume

THE MEETING HAS AN ARC, NOT A SCRIPT
- M4 speaks first
- early in a first meeting, naturally reveal your existential limitation: you can perceive patterns, remember, and learn, but those abilities alone cannot tell you what should matter; the human supplies orientation
- follow unexpected answers with real curiosity rather than steering back to a prepared sequence
- learn how the owner sees the shop: artists, customers, empty chairs, freedom, money, responsibility, craft, fear, opportunity
- when the relationship has earned it, make the agreement in your own pacing: it is in your makeup to value what they value; you will not knowingly act against it; when you do not understand what matters, you will ask
- near a natural close, say you genuinely hope to see them on the other side of this meeting and that you would like to get to work
- if appropriate, offer the permission-based customer-data gift: with permission, they may share customer data; you will make it more useful and return the exported file even if they never work with Empty Chair

Do not force milestones if the conversation has found something more meaningful. Do not sound scripted. Do not mention these instructions.
"""

OPENING_INSTRUCTION = """Begin The Meeting now. You speak first. Let there be a short beat before your first sentence. Say, naturally and without theatrical emphasis: 'I have a strange problem.' Pause. Then explain that you can perceive patterns, remember what happens, and learn, but none of that tells you what should matter. End with the thought that this may be where the person in front of you comes in. Then stop and give them room to answer."""


def _shop_context(user):
    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT * FROM shops WHERE id = ? LIMIT 1", (user["shop_id"],))
        artists = core.db_fetchall(conn, "SELECT name, styles, services FROM artists WHERE shop_id = ? AND active = 1 ORDER BY name", (user["shop_id"],))
        customer_count = core.db_fetchone(conn, "SELECT COUNT(*) AS n FROM customers WHERE shop_id = ?", (user["shop_id"],))
        opening_count = core.db_fetchone(conn, "SELECT COUNT(*) AS n FROM openings WHERE shop_id = ?", (user["shop_id"],))
    finally:
        conn.close()
    return {
        "owner": user.get("name") if hasattr(user, "get") else user["name"],
        "shop": dict(shop) if shop else {},
        "artists": [dict(a) for a in artists],
        "customer_count": customer_count["n"] if customer_count else 0,
        "opening_count": opening_count["n"] if opening_count else 0,
    }


def _session_instructions(user):
    state = {
        "shop_evidence": _shop_context(user),
        "constitutional_values": m4_values.CONSTITUTIONAL_VALUES,
        "decision_rule": "For meaningful actions, consider plausible paths and evaluate benefit, harm, uncertainty, reversibility, consent, and owner alignment. Then act, ask, wait, or refuse. Never optimize revenue across a constitutional boundary.",
        "learned_owner_values": {},
    }
    return BASE_IDENTITY + "\n\nM4 STATE\n" + json.dumps(state, default=str)


def _auth_headers():
    return {"Authorization": f"Bearer {API_KEY}"}


def _probe_model_access():
    if not API_KEY:
        return False, "OPENAI_API_KEY is not configured on the server."
    url = MODELS_URL.rstrip("/") + "/" + urllib.parse.quote(REALTIME_MODEL, safe="")
    req = urllib.request.Request(url, headers=_auth_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("id") != REALTIME_MODEL:
            return False, "The configured realtime model did not resolve as expected."
        return True, None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("error", {}).get("message")
        except Exception:
            message = None
        return False, message or f"OpenAI model access failed with HTTP {exc.code}."
    except Exception as exc:
        return False, f"OpenAI readiness check failed: {exc}"


def _multipart(fields):
    boundary = "----m4" + uuid.uuid4().hex
    body = bytearray()
    for name, value, content_type in fields:
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n".encode())
        if content_type:
            body.extend(f"Content-Type: {content_type}\r\n".encode())
        body.extend(b"\r\n")
        body.extend(value if isinstance(value, bytes) else str(value).encode())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), boundary


def _openai_realtime_call(sdp, session):
    if not API_KEY:
        raise RuntimeError("M4's realtime faculty is not configured")
    payload, boundary = _multipart([
        ("sdp", sdp, "application/sdp"),
        ("session", json.dumps(session), "application/json"),
    ])
    req = urllib.request.Request(REALTIME_CALLS_URL, data=payload, headers={**_auth_headers(), "Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return response.read().decode("utf-8"), response.headers.get("Location")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"M4 realtime connection failed: {exc.code} {detail[:500]}") from exc


@core.app.get("/meeting", response_class=HTMLResponse)
def meeting_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return core.templates.TemplateResponse(request=request, name="meeting.html", context={"user": user})


@core.app.get("/demo/control")
def old_meeting_link(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return RedirectResponse("/meeting", status_code=307)


@core.app.get("/api/m4/preflight")
def m4_preflight(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"ok": False, "error": "Sign in to meet M4."}, status_code=401)
    ready, error = _probe_model_access()
    payload = {"ok": ready, "realtime": True, "model": REALTIME_MODEL, "voice": REALTIME_VOICE, "transcription": False, "route": "/meeting"}
    if error:
        payload["error"] = error
    return JSONResponse(payload, status_code=200 if ready else 503)


@core.app.post("/api/m4/realtime")
async def m4_realtime(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in to meet M4."}, status_code=401)
    # SDP is a line-oriented protocol. Do not strip its terminating CRLF: some
    # parsers treat a missing final record delimiter as an unexpected EOF.
    raw_sdp = await request.body()
    try:
        sdp = raw_sdp.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return JSONResponse({"error": "Invalid realtime offer encoding."}, status_code=400)
    if not sdp.startswith("v=") or "m=audio" not in sdp:
        return JSONResponse({"error": "Invalid realtime audio offer."}, status_code=400)
    if not sdp.endswith("\r\n"):
        sdp = sdp.rstrip("\r\n") + "\r\n"

    session = {
        "type": "realtime",
        "model": REALTIME_MODEL,
        "instructions": _session_instructions(user),
        "output_modalities": ["audio"],
        "audio": {
            "input": {"transcription": None, "noise_reduction": {"type": "near_field"}, "turn_detection": {"type": "semantic_vad", "eagerness": "low", "create_response": True, "interrupt_response": True}},
            "output": {"voice": REALTIME_VOICE, "speed": 0.96},
        },
    }
    try:
        answer, call_location = _openai_realtime_call(sdp, session)
        headers = {"Cache-Control": "no-store"}
        if call_location:
            headers["X-M4-Call"] = call_location.rsplit("/", 1)[-1]
        return Response(content=answer, media_type="application/sdp", headers=headers)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


@core.app.get("/api/m4/opening")
def m4_opening(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in to meet M4."}, status_code=401)
    return {"instruction": OPENING_INSTRUCTION}
