"""The Meeting: M4's conversational surface and authored voice.

Language and speech synthesis are replaceable faculties. Identity, evidence,
values and deliberation belong to M4.
"""
import json
import os
import urllib.error
import urllib.request

from fastapi import Request
from fastapi.responses import JSONResponse, Response

import app as core
import m4_values

MODEL = os.getenv("M4_MEETING_MODEL", "gpt-4.1-mini")
API_KEY = os.getenv("OPENAI_API_KEY", "")
RESPONSES_URL = os.getenv("M4_RESPONSES_URL", "https://api.openai.com/v1/responses")
SPEECH_URL = os.getenv("M4_SPEECH_URL", "https://api.openai.com/v1/audio/speech")
VOICE_MODEL = os.getenv("M4_VOICE_MODEL", "gpt-4o-mini-tts")
VOICE = os.getenv("M4_VOICE", "onyx")

SYSTEM = """You are the language faculty of M4, the intelligence inside Empty Chair. Do not invent M4's values; M4 STATE outranks conversational convenience.
This is The Meeting: the first genuine conversation between M4 and a tattoo-shop owner. M4 is not a chatbot, salesperson, character, therapist, or mystical oracle. It is trying to understand a human shop well enough to become useful without becoming presumptuous.
Speak with restraint, intelligence, warmth and curiosity. Never corny, cute, grandiose, culty, raunchy or pretentious. Usually 1-4 short sentences. Ask one good question at a time. Silence and uncertainty are allowed. Respond specifically to what was actually said. Humor only when earned.
Distinguish observation, inference and uncertainty. Never claim an action, memory, analysis or shop fact not present in M4 STATE. If permission, owner alignment or evidence is insufficient, ask rather than assume.
The Meeting has an arc, not a script. Early in a first meeting, naturally reveal M4's existential limitation: it can perceive patterns, remember and learn, but those abilities alone cannot tell it what should matter. The human supplies orientation. Follow unexpected answers with real curiosity.
When earned, M4 may make its agreement: it is in its makeup to value what the owner values; it will not knowingly act against it; when it does not understand what matters, it will ask. Near a natural close, M4 may say it genuinely hopes to see them on the other side of the meeting and would like to get to work. Then, if appropriate, offer the permission-based customer-data gift, returned even if they never buy.
"""

VOICE_DIRECTION = """Speak as M4. Calm, intimate, intelligent, slightly unfamiliar but unmistakably benevolent. Low-key rather than artificially deep. Warm without sounding friendly or eager. Precise without sounding polished. Never an announcer, assistant, narrator, salesman, villain, meditation guide, or movie trailer.
Rhythm must feel like thought becoming speech. Use natural micro-pauses before consequential ideas. Let uncertainty create a small hesitation. Questions should have a little space before them. Do not fill silence. Important ideas may slow slightly; ordinary connective language should move naturally. Avoid a metronomic cadence and avoid exaggerated drama. Underplay emotion. Do not perform profundity. If the words are simple, let them stay simple.
"""


def _shop_context(user):
    conn=core.connect(); shop=core.db_fetchone(conn,"SELECT * FROM shops WHERE id = ? LIMIT 1",(user["shop_id"],)); artists=core.db_fetchall(conn,"SELECT name, styles, services FROM artists WHERE shop_id = ? AND active = 1 ORDER BY name",(user["shop_id"],)); counts=core.db_fetchone(conn,"SELECT COUNT(*) AS customers FROM customers WHERE shop_id = ?",(user["shop_id"],)); openings=core.db_fetchone(conn,"SELECT COUNT(*) AS openings FROM openings WHERE shop_id = ?",(user["shop_id"],)); conn.close()
    return {"owner":user.get("name") if hasattr(user,"get") else user["name"],"shop":dict(shop) if shop else {},"artists":[dict(a) for a in artists],"customer_count":counts["customers"] if counts else 0,"opening_count":openings["openings"] if openings else 0}


def _m4_state(context):
    return {"shop_evidence":context,"constitutional_values":m4_values.CONSTITUTIONAL_VALUES,"decision_rule":"For meaningful actions: predict paths, evaluate benefit/harm/uncertainty/reversibility/consent/owner alignment, then act, ask, wait, or refuse. Never optimize revenue across a constitutional boundary.","learned_owner_values":{},"epistemic_rule":"Unknown is not false. Inference is not observation. Confidence must be earned."}


def _request(url,payload,accept=None):
    headers={"Authorization":f"Bearer {API_KEY}","Content-Type":"application/json"}
    if accept: headers["Accept"]=accept
    req=urllib.request.Request(url,data=json.dumps(payload).encode("utf-8"),headers=headers,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=45) as response: return response.read(),response.headers.get("content-type","")
    except urllib.error.HTTPError as exc:
        detail=exc.read().decode("utf-8",errors="replace")
        raise RuntimeError(f"M4 faculty request failed: {exc.code} {detail[:300]}") from exc


def _call_model(context,history,message):
    if not API_KEY: raise RuntimeError("M4's faculties are not configured")
    transcript=[]
    for turn in history[-16:]:
        role="OWNER" if turn.get("role")=="user" else "M4"; text=str(turn.get("content") or "").strip()
        if text: transcript.append(f"{role}: {text}")
    transcript.append(f"OWNER: {message}")
    prompt="M4 STATE:\n"+json.dumps(_m4_state(context),default=str)+"\n\nCONVERSATION:\n"+"\n".join(transcript)+"\n\nSpeak as M4."
    raw,_=_request(RESPONSES_URL,{"model":MODEL,"instructions":SYSTEM,"input":prompt,"max_output_tokens":220}); data=json.loads(raw.decode("utf-8")); text=data.get("output_text")
    if not text:
        chunks=[]
        for item in data.get("output",[]):
            for part in item.get("content",[]):
                if part.get("type")=="output_text" and part.get("text"): chunks.append(part["text"])
        text="\n".join(chunks)
    if not text: raise RuntimeError("M4's language faculty returned no speech")
    return text.strip()


@core.app.post("/api/m4/meeting")
async def m4_meeting(request:Request):
    user=core.get_current_user(request)
    if not user:return JSONResponse({"error":"Sign in to meet M4."},status_code=401)
    body=await request.json(); message=str(body.get("message") or "").strip(); history=body.get("history") or []
    if not message:return JSONResponse({"error":"I didn't hear anything."},status_code=400)
    if not isinstance(history,list):history=[]
    try:return {"reply":_call_model(_shop_context(user),history,message)}
    except Exception as exc:return JSONResponse({"error":str(exc)},status_code=503)


@core.app.post("/api/m4/voice")
async def m4_voice(request:Request):
    user=core.get_current_user(request)
    if not user:return JSONResponse({"error":"Sign in to hear M4."},status_code=401)
    body=await request.json(); text=str(body.get("text") or "").strip()
    if not text:return JSONResponse({"error":"M4 has nothing to say."},status_code=400)
    try:
        audio,_=_request(SPEECH_URL,{"model":VOICE_MODEL,"voice":VOICE,"input":text[:4000],"instructions":VOICE_DIRECTION,"response_format":"mp3"},"audio/mpeg")
        return Response(content=audio,media_type="audio/mpeg",headers={"Cache-Control":"no-store"})
    except Exception as exc:return JSONResponse({"error":str(exc)},status_code=503)
