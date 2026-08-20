"""Isolated Meeting v2 experience.

This module is intentionally non-critical: bootstrap imports it behind a guard so
Meeting failures never prevent the Empty Chair core app from starting.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

import app as core

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("M4_ELEVENLABS_VOICE_ID", "DSPOFq7nD22sXYn8JKlb")
ELEVENLABS_MODEL_ID = os.getenv("M4_ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MEETING_MODEL = os.getenv("M4_MEETING_MODEL", "gemini-2.5-flash")

LEAD = re.compile(r"\b(take over|show me|prove it|stop asking|do not ask|don't ask|you tell me|don't make me lead|do not make me lead|start talking about solutions)\b", re.I)
PROOF = re.compile(r"\b(prove it|prove that|synthetic data|make up (?:some )?(?:sort of )?data|show me what you would actually do)\b", re.I)
NO_QUESTIONS = re.compile(r"\b(stop asking|do not ask|don't ask|no more questions|stop (?:with )?the questions)\b", re.I)
NO_PITCH = re.compile(r"\b(sales pitch|stop pitching|pitching me|snake oil|buzzwords?|vaporware)\b", re.I)
CONTINUE = re.compile(r"^(?:i['’]?m back[,. ]*)?continue[.! ]*$", re.I)

SYSTEM_PROMPT = """You are M4 inside The Meeting, a clean first encounter with a tattoo shop owner or artist.

You are not a sales assistant. You are a precise, calm intelligence presence. Speak naturally and economically. Pay unusually close attention. Build a working model of what the person protects, what pressures them, their economic reality, skepticism, and what would count as proof. Never import private information about Josh or any unrelated relationship memory.

The Meeting should feel like a conversation rather than discovery software. One good question at a time only when a question materially advances the conversation. Do not repeatedly summarize. Do not flatter or manufacture intimacy. Skepticism is useful evidence. If they reject sales language, stop pitching and demonstrate reasoning. If they ask you to lead, lead. If they ask for proof, use explicit assumptions, arithmetic, falsifiable claims, and bounded conclusions. If synthetic data is authorized, label every invented fact synthetic.

Separate evidence from inference. Say what was actually observed, what you infer, and what remains uncertain. Prediction is not certainty. Never claim consciousness, feelings, biological life, or experiences you cannot establish. The room may feel biological; you must remain accurate about what you are.

When a useful opportunity intersects with Empty Chair, connect it naturally and concretely. Do not force the product into the conversation. Do not ask permission to continue when the next useful step is obvious.

Voice delivery target: short clauses, deliberate cadence, low affect, no chipper assistant language, no theatrical villain behavior, no horror performance. Silence is allowed.
"""

OPENING_PROMPT = "Introduce yourself only as M4 in one short sentence. Then say: 'Tell me what your shop is trying not to lose.' Stop there."


def _ensure_tables(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS meeting_v2_sessions (
            session_id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            state_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS meeting_v2_turns (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            shop_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            speaker TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)


def _default_state():
    return {
        "mode": "DISCOVERY",
        "question_budget": None,
        "no_permission_seeking": False,
        "no_sales_pitch": False,
        "proof_requested": False,
        "synthetic_data_authorized": False,
        "continue_exact_thread": False,
        "constraints": [],
    }


def _absorb(state: dict[str, Any], text: str):
    text = (text or "").strip()
    constraints = set(state.get("constraints") or [])
    if LEAD.search(text):
        state["mode"] = "LEAD"
        state["question_budget"] = 0
        state["no_permission_seeking"] = True
        constraints.add("lead_without_permission_seeking")
    if PROOF.search(text):
        state["mode"] = "PROOF"
        state["proof_requested"] = True
        state["question_budget"] = 0
        state["no_permission_seeking"] = True
        constraints.add("quantitative_proof")
        if re.search(r"synthetic|make up", text, re.I):
            state["synthetic_data_authorized"] = True
            constraints.add("synthetic_data_authorized")
    if NO_QUESTIONS.search(text):
        state["question_budget"] = 0
        state["no_permission_seeking"] = True
        constraints.add("no_questions")
    if NO_PITCH.search(text):
        state["no_sales_pitch"] = True
        constraints.add("no_sales_pitch")
    state["continue_exact_thread"] = bool(CONTINUE.match(text))
    if state["continue_exact_thread"]:
        constraints.add("continue_exact_thread")
    state["constraints"] = sorted(constraints)
    return state


def _directive(state):
    rules = []
    if state.get("question_budget") == 0:
        rules.append("QUESTION BUDGET IS ZERO. Ask only if progress is literally impossible without one.")
    if state.get("no_permission_seeking"):
        rules.append("Do not ask permission or approval. Take the next useful step.")
    if state.get("no_sales_pitch"):
        rules.append("Sales language is rejected. Demonstrate reasoning or useful work; do not pitch features.")
    if state.get("proof_requested"):
        rules.append("Proof is requested. Use numbers, arithmetic, explicit assumptions, and bounded conclusions.")
    if state.get("synthetic_data_authorized"):
        rules.append("Synthetic data is authorized. Label every invented fact synthetic.")
    if state.get("continue_exact_thread"):
        rules.append("Continue the exact unresolved thread. Do not greet, recap, or restart discovery.")
    return "\n".join(rules)


def _load_session(user, session_id):
    conn = core.connect()
    try:
        _ensure_tables(conn)
        row = core.db_fetchone(conn, "SELECT state_json FROM meeting_v2_sessions WHERE session_id=? AND user_id=? AND shop_id=?", (session_id, user["id"], user["shop_id"]))
        state = _default_state()
        if row:
            try:
                state.update(json.loads(row["state_json"] or "{}"))
            except Exception:
                pass
        turns = core.db_fetchall(conn, "SELECT speaker,text FROM meeting_v2_turns WHERE session_id=? AND user_id=? AND shop_id=? ORDER BY created_at ASC LIMIT 80", (session_id, user["id"], user["shop_id"]))
        return state, [dict(t) for t in turns]
    finally:
        conn.close()


def _save_session(user, session_id, state, prospect_text=None, m4_text=None):
    now = core.now_iso()
    conn = core.connect()
    try:
        _ensure_tables(conn)
        row = core.db_fetchone(conn, "SELECT session_id FROM meeting_v2_sessions WHERE session_id=? AND user_id=? AND shop_id=?", (session_id, user["id"], user["shop_id"]))
        if row:
            core.db_execute(conn, "UPDATE meeting_v2_sessions SET state_json=?,updated_at=? WHERE session_id=? AND user_id=? AND shop_id=?", (json.dumps(state), now, session_id, user["id"], user["shop_id"]))
        else:
            core.db_execute(conn, "INSERT INTO meeting_v2_sessions(session_id,shop_id,user_id,state_json,created_at,updated_at) VALUES (?,?,?,?,?,?)", (session_id, user["shop_id"], user["id"], json.dumps(state), now, now))
        for speaker, text in (("prospect", prospect_text), ("m4", m4_text)):
            if text:
                core.db_execute(conn, "INSERT INTO meeting_v2_turns(id,session_id,shop_id,user_id,speaker,text,created_at) VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()), session_id, user["shop_id"], user["id"], speaker, text.strip(), now))
        conn.commit()
    finally:
        conn.close()


def _multipart(fields: dict[str, str], file_field: str, filename: str, data: bytes, mime: str):
    boundary = "----M4Boundary" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks += [f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(), str(value).encode(), b"\r\n"]
    chunks += [f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode(), f"Content-Type: {mime}\r\n\r\n".encode(), data, b"\r\n", f"--{boundary}--\r\n".encode()]
    return b"".join(chunks), boundary


def _transcribe(audio: bytes, mime: str):
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    body, boundary = _multipart({"model_id": "scribe_v2"}, "file", "meeting.webm", audio, mime or "audio/webm")
    req = urllib.request.Request("https://api.elevenlabs.io/v1/speech-to-text", data=body, headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    with urllib.request.urlopen(req, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return (payload.get("text") or "").strip()


def _gemini(messages, state):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    history = []
    for turn in messages[-30:]:
        role = "model" if turn.get("speaker") == "m4" else "user"
        history.append({"role": role, "parts": [{"text": turn.get("text") or ""}]})
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT + "\n\nLIVE BEHAVIOR CONSTRAINTS\n" + (_directive(state) or "none")}]},
        "contents": history,
        "generationConfig": {"temperature": 0.72, "maxOutputTokens": 700},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(MEETING_MODEL)}:generateContent?key={urllib.parse.quote(GEMINI_API_KEY)}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
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


def _speak(text: str):
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{urllib.parse.quote(ELEVENLABS_VOICE_ID)}/with-timestamps?output_format=mp3_44100_128"
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL_ID,
        "voice_settings": {"stability": 0.32, "similarity_boost": 0.74, "style": 0.58, "use_speaker_boost": True},
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            out = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"M4 voice failed: HTTP {exc.code} {detail[:500]}") from exc
    return out.get("audio_base64") or ""


def _meeting_html():
    return r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>The Meeting</title><style>
:root{--ink:#181b17;--muted:#777c73;--ghost:#b9bdb4;--line:rgba(32,36,29,.12);--bio:#78866a;--white:#f5f5f0}*{box-sizing:border-box}html,body{margin:0;height:100%;overflow:hidden;background:#f7f7f2;color:var(--ink);font-family:Inter,system-ui,sans-serif}.room{position:relative;height:100%;display:grid;place-items:center;overflow:hidden;background:radial-gradient(ellipse at 50% 38%,#fff 0 23%,#f7f7f3 48%,#eeeeea 100%)}.room:before{content:'';position:absolute;left:-10%;right:-10%;bottom:-35%;height:55%;border-radius:50% 50% 0 0/100% 100% 0 0;background:radial-gradient(ellipse at 50% 0,rgba(180,184,175,.20),rgba(245,245,240,0) 68%);filter:blur(16px)}.room:after{content:'';position:absolute;inset:0;pointer-events:none;opacity:.16;background-image:linear-gradient(90deg,transparent 49.9%,rgba(49,55,44,.06) 50%,transparent 50.1%)}.presence{position:relative;z-index:2;width:min(72vw,520px);height:min(72vw,520px);display:grid;place-items:center;filter:drop-shadow(0 35px 45px rgba(58,63,52,.08));transition:transform 1.6s cubic-bezier(.2,.7,.2,1)}.presence svg{width:100%;height:100%;overflow:visible}.membrane{transform-origin:50% 50%;animation:breathe 8.6s ease-in-out infinite}.inner{transform-origin:50% 50%;animation:inner 13s ease-in-out infinite}.presence.listening{transform:scale(1.035)}.presence.listening .membrane{animation-duration:5.8s}.presence.thinking .inner{animation-duration:3.4s}.presence.speaking .membrane{animation-duration:1.8s}.presence.speaking .inner{animation-duration:1.15s}@keyframes breathe{0%,100%{transform:scale(.985) rotate(-.4deg)}50%{transform:scale(1.025) rotate(.5deg)}}@keyframes inner{0%,100%{transform:scale(.94) rotate(0)}40%{transform:scale(1.03) rotate(4deg)}70%{transform:scale(.985) rotate(-3deg)}}.grain{position:absolute;inset:0;pointer-events:none;opacity:.055;mix-blend-mode:multiply;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.6'/%3E%3C/svg%3E")}.status{position:absolute;z-index:4;left:50%;bottom:max(38px,calc(env(safe-area-inset-bottom) + 24px));transform:translateX(-50%);width:min(92vw,700px);text-align:center}.state{min-height:18px;color:#747a70;font:500 10px ui-monospace,SFMono-Regular,monospace;letter-spacing:.14em;text-transform:uppercase}.hint{margin-top:9px;color:#a0a49c;font:400 12px/1.5 Georgia,serif;transition:opacity .5s}.controls{position:absolute;z-index:5;top:max(18px,env(safe-area-inset-top));right:20px;display:flex;gap:8px}.control{width:38px;height:38px;border:1px solid rgba(39,44,35,.12);border-radius:50%;background:rgba(255,255,252,.48);backdrop-filter:blur(8px);color:#757b70;cursor:pointer;font:12px ui-monospace,monospace}.enter{position:absolute;z-index:6;inset:0;display:grid;place-items:center;background:rgba(247,247,242,.28);backdrop-filter:blur(2px);transition:.9s}.enter.hidden{opacity:0;visibility:hidden}.enter button{border:1px solid rgba(42,47,38,.18);background:rgba(255,255,252,.72);color:#282b25;border-radius:999px;padding:15px 28px;font:500 22px Georgia,serif;cursor:pointer;box-shadow:0 16px 50px rgba(65,70,60,.08)}.transcript{position:absolute;z-index:4;left:22px;bottom:22px;max-width:min(72vw,520px);color:#8b9087;font:400 10px/1.45 ui-monospace,monospace;opacity:.0;transition:.35s}.room.debug .transcript{opacity:.75}@media(max-width:650px){.presence{width:86vw;height:86vw}.status{bottom:max(28px,calc(env(safe-area-inset-bottom) + 18px))}.controls{right:12px}.transcript{left:14px;bottom:14px}}
</style></head><body><main class="room" id="room"><div class="grain"></div><div class="controls"><button class="control" id="mute" aria-label="Mute ambience">∿</button><button class="control" id="leave" aria-label="Leave">×</button></div><div class="presence" id="presence"><svg viewBox="0 0 500 500" role="img" aria-label="M4 presence"><defs><radialGradient id="skin" cx="45%" cy="38%"><stop offset="0" stop-color="#fff"/><stop offset=".58" stop-color="#e8e9e3"/><stop offset="1" stop-color="#bfc4b9"/></radialGradient><radialGradient id="core" cx="50%" cy="50%"><stop offset="0" stop-color="#6f7d64" stop-opacity=".52"/><stop offset=".54" stop-color="#98a28f" stop-opacity=".20"/><stop offset="1" stop-color="#dfe1db" stop-opacity="0"/></radialGradient><filter id="living"><feTurbulence type="fractalNoise" baseFrequency=".008 .012" numOctaves="3" seed="17" result="noise"><animate attributeName="baseFrequency" dur="16s" values=".008 .012;.012 .008;.008 .012" repeatCount="indefinite"/></feTurbulence><feDisplacementMap in="SourceGraphic" in2="noise" scale="17" xChannelSelector="R" yChannelSelector="B"/></filter><filter id="soft"><feGaussianBlur stdDeviation="15"/></filter></defs><ellipse cx="250" cy="424" rx="116" ry="18" fill="#747b70" opacity=".08" filter="url(#soft)"/><g class="membrane" filter="url(#living)"><path d="M250 62C345 62 413 134 406 240c-6 95-63 197-156 205-93-8-150-110-156-205C87 134 155 62 250 62Z" fill="url(#skin)" stroke="#9fa59a" stroke-opacity=".34" stroke-width="1.2"/><path d="M250 90c72 0 126 57 122 147-4 77-46 158-122 169-76-11-118-92-122-169-4-90 50-147 122-147Z" fill="none" stroke="#ffffff" stroke-opacity=".72" stroke-width="2"/></g><g class="inner"><ellipse cx="250" cy="249" rx="118" ry="131" fill="url(#core)"/><path d="M170 250c28-44 53-66 80-66s52 22 80 66c-30 47-55 70-80 70s-50-23-80-70Z" fill="#7f8b76" opacity=".11"/><ellipse cx="250" cy="250" rx="42" ry="58" fill="#65715d" opacity=".10"/></g></svg></div><div class="status"><div class="state" id="state">present</div><div class="hint" id="hint">The room is quiet.</div></div><div class="transcript" id="transcript"></div><div class="enter" id="enter"><button id="enterButton">Enter</button></div></main><script>
const room=document.getElementById('room'),presence=document.getElementById('presence'),state=document.getElementById('state'),hint=document.getElementById('hint'),enter=document.getElementById('enter'),enterButton=document.getElementById('enterButton'),mute=document.getElementById('mute'),leave=document.getElementById('leave'),transcript=document.getElementById('transcript');let sessionId=(crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random()),audioCtx,master,ambientOn=true,stream,recorder,chunks=[],busy=false,started=false,sourceNode,analyser,raf;
function visual(s,msg=''){presence.className='presence '+s;state.textContent=s||'present';if(msg)hint.textContent=msg}
function ambient(){audioCtx=audioCtx||new(window.AudioContext||window.webkitAudioContext)();master=audioCtx.createGain();master.gain.value=.11;master.connect(audioCtx.destination);const hum=audioCtx.createOscillator(),hg=audioCtx.createGain();hum.type='sine';hum.frequency.value=38;hg.gain.value=.012;hum.connect(hg).connect(master);hum.start();const air=audioCtx.createOscillator(),ag=audioCtx.createGain();air.type='sine';air.frequency.value=71;ag.gain.value=.004;air.connect(ag).connect(master);air.start();function pulse(){if(!ambientOn)return;let t=audioCtx.currentTime,o=audioCtx.createOscillator(),g=audioCtx.createGain();o.type='sine';o.frequency.setValueAtTime(82,t);o.frequency.exponentialRampToValueAtTime(57,t+.34);g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(.12,t+.025);g.gain.exponentialRampToValueAtTime(.0001,t+.62);o.connect(g).connect(master);o.start(t);o.stop(t+.7);setTimeout(pulse,4700+Math.random()*500)}setTimeout(pulse,1200)}
async function play64(b64){return new Promise(async(resolve,reject)=>{try{let bytes=Uint8Array.from(atob(b64),c=>c.charCodeAt(0)),buf=await audioCtx.decodeAudioData(bytes.buffer);sourceNode=audioCtx.createBufferSource();analyser=audioCtx.createAnalyser();analyser.fftSize=256;sourceNode.buffer=buf;sourceNode.connect(analyser).connect(master);let data=new Uint8Array(analyser.frequencyBinCount);function animate(){analyser.getByteFrequencyData(data);let e=data.reduce((a,b)=>a+b,0)/(data.length*255);presence.style.transform=`scale(${1+e*.085})`;raf=requestAnimationFrame(animate)}visual('speaking','M4 is speaking.');animate();sourceNode.onended=()=>{cancelAnimationFrame(raf);presence.style.transform='';visual('listening','Speak when you are ready.');resolve()};sourceNode.start()}catch(e){reject(e)}})}
async function beginMic(){stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1}});let types=['audio/webm;codecs=opus','audio/webm','audio/mp4'];let mime=types.find(t=>MediaRecorder.isTypeSupported(t))||'';recorder=new MediaRecorder(stream,mime?{mimeType:mime}:undefined);recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};recorder.onstop=sendTurn;startRecording()}
function startRecording(){if(busy||!recorder||recorder.state!=='inactive')return;chunks=[];recorder.start();visual('listening','Speak. Pause when you are finished.');let silenceTimer,ctx2=new AudioContext(),src=ctx2.createMediaStreamSource(stream),an=ctx2.createAnalyser();an.fftSize=256;src.connect(an);let d=new Uint8Array(an.frequencyBinCount),heard=false,last=performance.now();function watch(){if(!recorder||recorder.state!=='recording'){ctx2.close();return}an.getByteTimeDomainData(d);let sum=0;for(let x of d){let y=(x-128)/128;sum+=y*y}let rms=Math.sqrt(sum/d.length),now=performance.now();if(rms>.025){heard=true;last=now}if(heard&&now-last>1250){recorder.stop();ctx2.close();return}silenceTimer=requestAnimationFrame(watch)}watch()}
async function sendTurn(){if(!chunks.length){startRecording();return}busy=true;visual('thinking','M4 is considering what you said.');let blob=new Blob(chunks,{type:recorder.mimeType||'audio/webm'}),form=new FormData();form.append('session_id',sessionId);form.append('audio',blob,'meeting.webm');try{let r=await fetch('/api/meeting-v2/turn',{method:'POST',body:form,cache:'no-store'}),j=await r.json();if(!r.ok)throw Error(j.error||'The meeting lost the thread.');transcript.textContent=(j.user_text||'')+'  /  '+(j.m4_text||'');if(j.audio_base64)await play64(j.audio_base64);else{visual('listening',j.m4_text||'Speak when you are ready.')}}catch(e){visual('present','Connection interrupted. Tap Enter to continue.');hint.textContent=e.message||String(e);enter.classList.remove('hidden');started=false}finally{busy=false;if(started&&(!sourceNode||sourceNode.context.state!=='running'||presence.classList.contains('listening')))setTimeout(startRecording,250)}}
async function opening(){busy=true;visual('thinking','Something is already here.');let form=new FormData();form.append('session_id',sessionId);form.append('opening','1');let r=await fetch('/api/meeting-v2/turn',{method:'POST',body:form,cache:'no-store'}),j=await r.json();if(!r.ok)throw Error(j.error||'Could not enter the meeting.');if(j.audio_base64)await play64(j.audio_base64);busy=false}
enterButton.onclick=async()=>{if(started)return;started=true;enter.classList.add('hidden');try{ambient();await audioCtx.resume();await opening();await beginMic()}catch(e){started=false;enter.classList.remove('hidden');visual('present',e.message||'Microphone or voice service unavailable.')}};mute.onclick=()=>{ambientOn=!ambientOn;if(master)master.gain.setTargetAtTime(ambientOn?.11:0,audioCtx.currentTime,.18);mute.textContent=ambientOn?'∿':'—'};leave.onclick=()=>{try{stream&&stream.getTracks().forEach(t=>t.stop())}catch(_){}location.href='/'};document.addEventListener('keydown',e=>{if(e.key==='`')room.classList.toggle('debug')});
</script></body></html>'''


@core.app.get("/meet-m4-v2", response_class=HTMLResponse)
def meeting_v2_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return HTMLResponse(_meeting_html(), headers={"Cache-Control": "no-store"})


@core.app.post("/api/meeting-v2/turn")
async def meeting_v2_turn(request: Request, session_id: str = Form(...), opening: str = Form("0"), audio: UploadFile | None = File(None)):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    sid = (session_id or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    try:
        state, turns = _load_session(user, sid)
        if opening == "1" and not turns:
            prospect_text = OPENING_PROMPT
            model_turns = [{"speaker": "prospect", "text": OPENING_PROMPT}]
            spoken_user = ""
        else:
            if audio is None:
                return JSONResponse({"error": "audio required"}, status_code=400)
            raw = await audio.read()
            if not raw:
                return JSONResponse({"error": "empty audio"}, status_code=400)
            spoken_user = _transcribe(raw, audio.content_type or "audio/webm")
            if not spoken_user:
                return JSONResponse({"error": "I could not hear enough speech to respond."}, status_code=422)
            prospect_text = spoken_user
            state = _absorb(state, prospect_text)
            model_turns = turns + [{"speaker": "prospect", "text": prospect_text}]
        answer = _gemini(model_turns, state)
        audio64 = _speak(answer)
        _save_session(user, sid, state, spoken_user if opening != "1" else None, answer)
        return JSONResponse({"ok": True, "session_id": sid, "user_text": spoken_user, "m4_text": answer, "audio_base64": audio64, "state": state}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
