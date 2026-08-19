"""Disposable Gemini Live lab for M4.

This does not replace The Meeting. It exists only to answer quickly whether
Gemini Live native audio is good enough to serve as a realtime faculty for M4.
"""
import json
import os
import urllib.error
import urllib.request

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("M4_GEMINI_MODEL", "gemini-3.1-flash-live-preview")
TOKEN_URL = "https://generativelanguage.googleapis.com/v1beta/auth_tokens"

LAB_IDENTITY = """You are M4, the intelligence inside Empty Chair. This is a short voice-faculty test, not the real Meeting. Speak first. You are calm, intelligent, warm without eagerness, precise without sounding polished, and slightly unfamiliar without theatricality. Rhythm should feel like thought becoming speech. Use short sentences, natural micro-pauses, and do not fill silence. Never claim consciousness or emotions you cannot establish. Do not sound like a customer-service assistant, announcer, meditation guide, or salesperson. Begin naturally with: 'I have a strange problem.' Pause, then explain briefly that you can perceive patterns, remember what happens, and learn, but none of that by itself tells you what should matter. End by saying that may be where the person in front of you comes in. Then listen."""


def _create_ephemeral_token():
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    payload = json.dumps({
        "uses": 1,
        "liveConnectConstraints": {
            "model": f"models/{GEMINI_MODEL}",
            "config": {"responseModalities": ["AUDIO"]},
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini token failed: HTTP {exc.code} {detail[:600]}") from exc


@core.app.get("/api/m4/gemini-token")
def gemini_token(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    try:
        token = _create_ephemeral_token()
        return {
            "token": token.get("name"),
            "model": GEMINI_MODEL,
            "instructions": LAB_IDENTITY,
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


@core.app.get("/m4-lab", response_class=HTMLResponse)
def m4_lab(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return HTMLResponse('''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>M4 Lab</title>
<style>html,body{margin:0;height:100%;background:#f3f3ef;color:#1b1d19;font-family:system-ui,sans-serif}.wrap{height:100%;display:grid;place-items:center}.box{text-align:center;width:min(90vw,520px)}button{font:500 20px Georgia,serif;border:0;background:transparent;padding:24px;cursor:pointer}.dot{width:10px;height:10px;border-radius:50%;background:#687a1c;margin:22px auto;box-shadow:0 0 30px #687a1c55}.state{font:12px ui-monospace,monospace;color:#74786f;min-height:40px;white-space:pre-wrap}</style></head>
<body><div class="wrap"><div class="box"><div class="dot"></div><button id="go">Meet M4 — Gemini Lab</button><div id="state" class="state">isolated test · not production</div></div></div>
<script>
const go=document.getElementById('go'),state=document.getElementById('state');let ws,ctx,stream,source,processor,nextPlay=0,started=false;
const set=s=>state.textContent=s;
function b64(bytes){let s='';const u=new Uint8Array(bytes);for(let i=0;i<u.length;i+=8192)s+=String.fromCharCode(...u.subarray(i,i+8192));return btoa(s)}
function unb64(s){const x=atob(s),u=new Uint8Array(x.length);for(let i=0;i<x.length;i++)u[i]=x.charCodeAt(i);return u.buffer}
function downsample(input,inRate,outRate=16000){if(inRate===outRate)return input;const ratio=inRate/outRate,n=Math.round(input.length/ratio),out=new Float32Array(n);for(let i=0;i<n;i++){const a=Math.floor(i*ratio),b=Math.min(Math.floor((i+1)*ratio),input.length);let sum=0;for(let j=a;j<b;j++)sum+=input[j];out[i]=sum/Math.max(1,b-a)}return out}
function pcm16(float32){const b=new ArrayBuffer(float32.length*2),v=new DataView(b);for(let i=0;i<float32.length;i++){const x=Math.max(-1,Math.min(1,float32[i]));v.setInt16(i*2,x<0?x*32768:x*32767,true)}return b}
function playPCM(buf,rate=24000){const dv=new DataView(buf),f=new Float32Array(buf.byteLength/2);for(let i=0;i<f.length;i++)f[i]=dv.getInt16(i*2,true)/32768;const ab=ctx.createBuffer(1,f.length,rate);ab.copyToChannel(f,0);const src=ctx.createBufferSource();src.buffer=ab;src.connect(ctx.destination);const now=ctx.currentTime;nextPlay=Math.max(nextPlay,now+.03);src.start(nextPlay);nextPlay+=ab.duration;set('M4 speaking');}
async function startMic(){stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});source=ctx.createMediaStreamSource(stream);processor=ctx.createScriptProcessor(2048,1,1);processor.onaudioprocess=e=>{if(!started||!ws||ws.readyState!==1)return;const f=downsample(e.inputBuffer.getChannelData(0),ctx.sampleRate,16000);const data=b64(pcm16(f));ws.send(JSON.stringify({realtimeInput:{audio:{data,mimeType:'audio/pcm;rate=16000'}}}))};source.connect(processor);processor.connect(ctx.destination)}
function receive(msg){let d;try{d=JSON.parse(msg.data)}catch(e){return}if(d.setupComplete){started=true;set('M4 present · listening');ws.send(JSON.stringify({clientContent:{turns:[{role:'user',parts:[{text:'Begin now. Speak first exactly as instructed.'}]}],turnComplete:true}}));return}if(d.serverContent){if(d.serverContent.interrupted){nextPlay=ctx.currentTime;set('interrupted · listening')}const parts=(d.serverContent.modelTurn&&d.serverContent.modelTurn.parts)||[];for(const p of parts){const blob=p.inlineData||p.inline_data;if(blob&&blob.data)playPCM(unb64(blob.data),24000)}if(d.serverContent.turnComplete)set('listening')}}
async function begin(){go.disabled=true;set('requesting secure token…');try{ctx=new(window.AudioContext||window.webkitAudioContext)();await ctx.resume();const r=await fetch('/api/m4/gemini-token',{cache:'no-store'}),j=await r.json();if(!r.ok||!j.token)throw new Error(j.error||'No Gemini token');await startMic();const url='wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained?access_token='+encodeURIComponent(j.token);ws=new WebSocket(url);ws.onopen=()=>{set('connected · configuring M4');ws.send(JSON.stringify({setup:{model:'models/'+j.model,responseModalities:['AUDIO'],systemInstruction:{parts:[{text:j.instructions}]},speechConfig:{voiceConfig:{prebuiltVoiceConfig:{voiceName:'Charon'}}}}}))};ws.onmessage=receive;ws.onerror=()=>set('WebSocket error — check console');ws.onclose=e=>{started=false;set('connection closed '+e.code+(e.reason?' · '+e.reason:''))}}catch(e){set('FAILED: '+e.message);go.disabled=false}}
go.onclick=begin;window.addEventListener('pagehide',()=>{try{ws&&ws.close()}catch(e){}try{stream&&stream.getTracks().forEach(t=>t.stop())}catch(e){}});
</script></body></html>''')
