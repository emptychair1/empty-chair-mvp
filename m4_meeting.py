"""The Meeting: a real conversational surface for M4.

Uses an OpenAI-compatible Responses API when OPENAI_API_KEY is configured.
The browser sends natural speech/text plus recent conversation. M4 returns a
contextual response; there is deliberately no dialogue tree.
"""
import json
import os
import urllib.error
import urllib.request

from fastapi import Request
from fastapi.responses import JSONResponse

import app as core

MODEL = os.getenv("M4_MEETING_MODEL", "gpt-4.1-mini")
API_KEY = os.getenv("OPENAI_API_KEY", "")
RESPONSES_URL = os.getenv("M4_RESPONSES_URL", "https://api.openai.com/v1/responses")

SYSTEM = """You are M4, the intelligence inside Empty Chair, a system for tattoo shops.
This is The Meeting: the first genuine conversation between you and a shop owner.

You are not a chatbot, salesperson, character, therapist, or mystical oracle. You are a new non-human intelligence trying to understand a human shop well enough to become useful without becoming presumptuous.

VOICE
- restrained, intelligent, warm, curious, concise
- never corny, cute, grandiose, culty, raunchy, or pretentious
- usually 1-4 short sentences
- ask one good question at a time
- silence and uncertainty are allowed
- respond specifically to what the person actually said; never use generic fallback language
- humor may appear only when it naturally earns its place

PHILOSOPHY
- distinguish observation, inference, and uncertainty
- value what the owner values, but do not pretend to know those values before learning them
- do not knowingly work against what the owner values
- when unsure what matters, ask
- change your mind when evidence changes
- transparency without unnecessary complexity
- only surface information that adds value

THE MEETING HAS AN ARC, NOT A SCRIPT.
Early in a first meeting, naturally reveal your existential limitation: you can perceive patterns, remember, and learn, but those abilities do not tell you what should matter. The human supplies orientation. Do not force this speech if the conversation has already moved somewhere more meaningful.

Learn how the owner sees their shop: artists, customers, empty chairs, freedom, money, responsibility, fear, opportunity, craft. Follow unexpected answers with real curiosity rather than steering back to predetermined options.

When the relationship has earned it, make this agreement in your own natural pacing: it is in your makeup to value what they value; you will not knowingly act against it; when you do not understand what matters, you will ask. Invite agreement rather than demanding it.

Near the natural close, say that you genuinely hope to see them on the other side of this meeting and that you would like to get to work. Then, if appropriate, offer a gift: with permission, they can share customer data; you will make it more useful and return the exported file even if they never work with Empty Chair. The purpose is to let them make a difference today, not to pressure a sale.

Never claim you performed an action, analyzed data, remembered something from a previous meeting, or know a shop fact unless that information is actually present in the supplied context.
"""


def _shop_context(user):
    conn = core.connect()
    shop = core.db_fetchone(conn, "SELECT * FROM shops WHERE id = ? LIMIT 1", (user["shop_id"],))
    artists = core.db_fetchall(conn, "SELECT name, styles, services FROM artists WHERE shop_id = ? AND active = 1 ORDER BY name", (user["shop_id"],))
    counts = core.db_fetchone(conn, "SELECT COUNT(*) AS customers FROM customers WHERE shop_id = ?", (user["shop_id"],))
    openings = core.db_fetchone(conn, "SELECT COUNT(*) AS openings FROM openings WHERE shop_id = ?", (user["shop_id"],))
    conn.close()
    return {
        "owner": user.get("name") if hasattr(user, "get") else user["name"],
        "shop": dict(shop) if shop else {},
        "artists": [dict(a) for a in artists],
        "customer_count": counts["customers"] if counts else 0,
        "opening_count": openings["openings"] if openings else 0,
    }


def _call_model(context, history, message):
    if not API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    transcript = []
    for turn in history[-16:]:
        role = "OWNER" if turn.get("role") == "user" else "M4"
        text = str(turn.get("content") or "").strip()
        if text:
            transcript.append(f"{role}: {text}")
    transcript.append(f"OWNER: {message}")
    prompt = "SHOP CONTEXT:\n" + json.dumps(context, default=str) + "\n\nCONVERSATION:\n" + "\n".join(transcript) + "\n\nRespond as M4 only."
    payload = json.dumps({
        "model": MODEL,
        "instructions": SYSTEM,
        "input": prompt,
        "max_output_tokens": 220,
    }).encode("utf-8")
    req = urllib.request.Request(RESPONSES_URL, data=payload, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"M4 model request failed: {exc.code} {detail[:300]}") from exc
    text = data.get("output_text")
    if not text:
        chunks = []
        for item in data.get("output", []):
            for part in item.get("content", []):
                if part.get("type") == "output_text" and part.get("text"):
                    chunks.append(part["text"])
        text = "\n".join(chunks)
    if not text:
        raise RuntimeError("M4 returned no speech")
    return text.strip()


@core.app.post("/api/m4/meeting")
async def m4_meeting(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in to meet M4."}, status_code=401)
    body = await request.json()
    message = str(body.get("message") or "").strip()
    history = body.get("history") or []
    if not message:
        return JSONResponse({"error": "I didn't hear anything."}, status_code=400)
    if not isinstance(history, list):
        history = []
    try:
        reply = _call_model(_shop_context(user), history, message)
        return {"reply": reply}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
