"""Disposable Gemini Live identity lab for M4.

Gemini is only a realtime language/audio faculty here. M4's identity, shop evidence,
constitutional values, relationship memory and Meeting behavior come from Empty Chair.
Production /meeting remains untouched.
"""
import json
import os
import urllib.error
import urllib.request

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core
import m4_meeting
import m4_memory

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("M4_GEMINI_MODEL", "gemini-3.1-flash-live-preview")
GEMINI_VOICE = os.getenv("M4_GEMINI_VOICE", "Achernar")
TOKEN_URL = "https://generativelanguage.googleapis.com/v1beta/auth_tokens"
LAB_OPENING = "Say exactly: Is anyone there? Then stop and wait for the person to answer."


def _create_ephemeral_token():
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    payload = json.dumps({"uses": 1}).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=payload, headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini token failed: HTTP {exc.code} {detail[:600]}") from exc


def _instructions_with_memory(user):
    recent = m4_memory.load_recent(user, limit=40)
    memory_note = (
        "\n\nPERSISTENT RELATIONSHIP MEMORY EVIDENCE\n"
        "These are hidden audio transcriptions from prior conversations. Treat owner speech as direct conversational evidence, but remember transcription can contain errors. Do not silently convert your own prior words into owner beliefs, and do not turn inference into remembered fact.\n"
        + json.dumps(recent, default=str)
    )
    return m4_meeting._session_instructions(user) + memory_note


@core.app.get("/api/m4/gemini-token")
def gemini_token(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    try:
        token = _create_ephemeral_token()
        return {"token": token.get("name"), "model": GEMINI_MODEL, "voice": GEMINI_VOICE, "instructions": _instructions_with_memory(user), "opening": LAB_OPENING}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


@core.app.post("/api/m4/relationship-turn")
async def relationship_turn(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    try:
        data = await request.json()
        ok = m4_memory.store_turn(
            user,
            str(data.get("session_id") or ""),
            str(data.get("speaker") or ""),
            str(data.get("text") or ""),
        )
        return {"ok": bool(ok)}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@core.app.get("/api/m4/relationship-transcript")
def relationship_transcript(request: Request, limit: int = 200):
    """Private transcript evidence for the signed-in owner; never exposed cross-user."""
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    try:
        turns = m4_memory.load_transcript(user, limit=limit)
        sessions = []
        by_id = {}
        for turn in turns:
            sid = turn.get("session_id") or "unknown"
            if sid not in by_id:
                session = {"session_id": sid, "turns": []}
                by_id[sid] = session
                sessions.append(session)
            by_id[sid]["turns"].append({
                "speaker": turn.get("speaker"),
                "text": turn.get("text"),
                "source": turn.get("source"),
                "created_at": turn.get("created_at"),
            })
        return JSONResponse({"count": len(turns), "sessions": sessions}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@core.app.get("/m4-lab", response_class=HTMLResponse)
def m4_lab(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return HTMLResponse('''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>M4 Identity Lab</title>
<style>html,body{margin:0;height:100%;background:#f3f3ef;color:#1b1d19;font-family:system-ui,sans-serif}.wrap{height:100%;display:grid;place-items:center;padding:24px;box-sizing:border-box}.box{text-align:center;width:min(92vw,560px)}h1{font:500 27px Georgia,serif;margin:0 0 10px}.sub{font:12px ui-monospace,monospace;color:#74786f;line-height:1.55;margin-bottom:24px}.go{font:500 20px Georgia,serif;border:1px solid #c8cbc2;border-radius:999px;background:transparent;padding:14px 24px;cursor:pointer;color:#252821}.dot{width:10px;height:10px;border-radius:50%;background:#687a1c;margin:18px auto;box-shadow:0 0 30px #687a1c55}.state{font:12px ui-monospace,monospace;color:#74786f;min-height:42px;white-space:pre-wrap}.note{font:11px ui-monospace,monospace;color:#92968d;margin-top:18px;line-height:1.5}</style></head>
<body><div class="wrap"><div class="box"><div class="dot"></div><h1>M4 identity test</h1><div class="sub">actual M4 identity + actual shop state + actual constitutional values<br>persistent relationship memory · Achernar = temporary voice</div><button class="go" id="go">Meet M4 candidate</button><div id="state" class="state">Production Meeting is untouched.</div><div class="note">Conversation memory is captured invisibly. No transcript is shown in the experience.</div></div></div>
<script>
const go=document.getElementById('go'),state=document.getElementById('state');let ws,ctx,stream,source,processor,started=false,handshakeTimer=null,m4Speaking=false,userSpeaking=false,lastVoiceAt=0,voiceStartedAt=0,audioQueue=[],audioQueuedSamples=0,audioSource=null,audioGeneration=0,serverTurnComplete=false,inputTranscript='',outputTranscript='';
const PLAY_RATE=24000,START_BUFFER_SAMPLES=7200,REFILL_BUFFER_SAMPLES=3600,sessionId=(crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random());
const set=s=>state.textContent=s;
function b64(bytes){let s='';const u=new Uint8Array(bytes);for(let i=0;i<u.length;i+=8192)s+=String.fromCharCode(...u.subarray(i,i+8192));return btoa(s)}
function unb64(s){const x=atob(s),u=new Uint8Array(x.length);for(let i=0;i<x.length;i++)u[i]=x.charCodeAt(i);return u.buffer}
function downsample(input,inRate,outRate=16000){if(inRate===outRate)return input;const ratio=inRate/outRate,n=Math.round(input.length/ratio),out=new Float32Array(n);for(let i=0;i<n;i++){const a=Math.floor(i*ratio),b=Math.min(Math.floor((i+1)*ratio),input.length);let sum=0;for(let j=a;j<b;j++)sum+=input[j];out[i]=sum/Math.max(1,b-a)}return out}
function pcm16(float32){const b=new ArrayBuffer(float32.length*2),v=new DataView(b);for(let i=0;i<float32.length;i++){const x=Math.max(-1,Math.min(1,float32[i]));v.setInt16(i*2,x<0?x*32768:x*32767,true)}return b}
function send(obj){if(ws&&ws.readyState===1)ws.send(JSON.stringify(obj))}
function pcmFloat(buf){const dv=new DataView(buf),f=new Float32Array(buf.byteLength/2);for(let i=0;i<f.length;i++)f[i]=dv.getInt16(i*2,true)/32768;return f}
function stopPlayback(){audioGeneration++;if(audioSource){try{audioSource.stop()}catch(e){}}audioSource=null;audioQueue=[];audioQueuedSamples=0;m4Speaking=false;serverTurnComplete=false}
function enqueuePCM(buf){const f=pcmFloat(buf);audioQueue.push(f);audioQueuedSamples+=f.length;m4Speaking=true;set('M4 candidate speaking');pumpAudio(false)}
function takeQueuedSamples(){if(!audioQueuedSamples)return null;const out=new Float32Array(audioQueuedSamples);let p=0;for(const chunk of audioQueue){out.set(chunk,p);p+=chunk.length}audioQueue=[];audioQueuedSamples=0;return out}
function pumpAudio(force){if(audioSource)return;if(!audioQueuedSamples){if(serverTurnComplete){m4Speaking=false;set('listening')}return}const threshold=m4Speaking&&serverTurnComplete?1:(m4Speaking?REFILL_BUFFER_SAMPLES:START_BUFFER_SAMPLES);if(!force&&audioQueuedSamples<threshold&&!serverTurnComplete)return;const samples=takeQueuedSamples(),generation=audioGeneration,ab=ctx.createBuffer(1,samples.length,PLAY_RATE);ab.copyToChannel(samples,0);const src=ctx.createBufferSource();src.buffer=ab;src.connect(ctx.destination);audioSource=src;src.onended=()=>{if(generation!==audioGeneration)return;audioSource=null;if(audioQueuedSamples)pumpAudio(serverTurnComplete);else if(serverTurnComplete){m4Speaking=false;set('listening')}};src.start(ctx.currentTime+.03)}
function beginUserTurn(){if(userSpeaking)return;userSpeaking=true;voiceStartedAt=performance.now();send({realtimeInput:{activityStart:{}}});set('hearing you')}
function endUserTurn(){if(!userSpeaking)return;userSpeaking=false;send({realtimeInput:{activityEnd:{}}});set('thinking')}
function mergeTranscript(current,next){next=(next||'').trim();if(!next)return current;if(next.startsWith(current))return next;if(current.endsWith(next))return current;return (current+(current&&next?' ':'')+next).trim()}
async function remember(speaker,text){text=(text||'').trim();if(!text)return;try{await fetch('/api/m4/relationship-turn',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,speaker,text})})}catch(e){console.warn('memory write failed',e)}}
function flushMemory(){const owner=inputTranscript,m4=outputTranscript;inputTranscript='';outputTranscript='';if(owner)remember('owner',owner);if(m4)remember('m4',m4)}
async function startMic(){stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:false,channelCount:1},video:false});source=ctx.createMediaStreamSource(stream);processor=ctx.createScriptProcessor(2048,1,1);processor.onaudioprocess=e=>{if(!started||m4Speaking||!ws||ws.readyState!==1)return;const f=downsample(e.inputBuffer.getChannelData(0),ctx.sampleRate,16000);let energy=0;for(let i=0;i<f.length;i++)energy+=f[i]*f[i];const rms=Math.sqrt(energy/Math.max(1,f.length)),now=performance.now();if(rms>=0.018){lastVoiceAt=now;beginUserTurn()}if(userSpeaking){send({realtimeInput:{audio:{data:b64(pcm16(f)),mimeType:'audio/pcm;rate=16000'}}});if(now-lastVoiceAt>700&&now-voiceStartedAt>250)endUserTurn()}};source.connect(processor);processor.connect(ctx.destination)}
function cleanup(){flushMemory();started=false;userSpeaking=false;if(handshakeTimer)clearTimeout(handshakeTimer);handshakeTimer=null;stopPlayback();try{ws&&ws.close()}catch(e){}ws=null;try{processor&&processor.disconnect()}catch(e){}processor=null;try{source&&source.disconnect()}catch(e){}source=null;try{stream&&stream.getTracks().forEach(t=>t.stop())}catch(e){}stream=null}
async function decodeFrame(data){if(typeof data==='string')return data;if(data instanceof Blob)return await data.text();if(data instanceof ArrayBuffer)return new TextDecoder().decode(data);return String(data)}
async function receive(msg){let raw='';try{raw=await decodeFrame(msg.data)}catch(e){set('FAILED decoding server frame: '+e.message);return}let d;try{d=JSON.parse(raw)}catch(e){set('SERVER FRAME: '+raw.slice(0,240));return}if(d.setupComplete){if(handshakeTimer)clearTimeout(handshakeTimer);started=true;set('M4 candidate present');send({clientContent:{turns:[{role:'user',parts:[{text:window.__opening}]}],turnComplete:true}});return}if(d.error){set('GEMINI ERROR: '+JSON.stringify(d.error).slice(0,360));return}if(d.serverContent){const sc=d.serverContent;if(sc.inputTranscription&&sc.inputTranscription.text)inputTranscript=mergeTranscript(inputTranscript,sc.inputTranscription.text);if(sc.outputTranscription&&sc.outputTranscription.text)outputTranscript=mergeTranscript(outputTranscript,sc.outputTranscription.text);if(sc.interrupted){stopPlayback();set('interrupted · listening')}const parts=(sc.modelTurn&&sc.modelTurn.parts)||[];for(const p of parts){const blob=p.inlineData||p.inline_data;if(blob&&blob.data)enqueuePCM(unb64(blob.data))}if(sc.turnComplete){serverTurnComplete=true;pumpAudio(true);flushMemory()}return}}
async function begin(){go.disabled=true;cleanup();set('Loading M4 + relationship memory…');try{ctx=ctx||new(window.AudioContext||window.webkitAudioContext)();await ctx.resume();const r=await fetch('/api/m4/gemini-token',{cache:'no-store'}),j=await r.json();if(!r.ok||!j.token)throw new Error(j.error||'No Gemini token');window.__opening=j.opening;await startMic();const url='wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained?access_token='+encodeURIComponent(j.token);ws=new WebSocket(url);ws.binaryType='arraybuffer';ws.onopen=()=>{set('connected · loading M4 identity');send({setup:{model:'models/'+j.model,generationConfig:{responseModalities:['AUDIO'],speechConfig:{voiceConfig:{prebuiltVoiceConfig:{voiceName:j.voice||'Achernar'}}}},realtimeInputConfig:{automaticActivityDetection:{disabled:true}},inputAudioTranscription:{},outputAudioTranscription:{},systemInstruction:{parts:[{text:j.instructions}]}}});handshakeTimer=setTimeout(()=>{if(!started)set('connected · no setupComplete after 8s')},8000)};ws.onmessage=receive;ws.onerror=()=>set('WebSocket error');ws.onclose=e=>{flushMemory();if(started)set('connection closed '+e.code+(e.reason?' · '+e.reason:''));started=false}}catch(e){set('FAILED: '+e.message)}finally{go.disabled=false}}
go.onclick=begin;window.addEventListener('pagehide',cleanup);
</script></body></html>''' )
