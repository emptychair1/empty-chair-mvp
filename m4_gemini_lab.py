"""Disposable Gemini Live identity lab for M4.

Gemini is only a realtime language/audio faculty here. M4's identity, shop evidence,
constitutional values and Meeting behavior come from Empty Chair's existing M4 code.
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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("M4_GEMINI_MODEL", "gemini-3.1-flash-live-preview")
GEMINI_VOICE = os.getenv("M4_GEMINI_VOICE", "Achernar")
TOKEN_URL = "https://generativelanguage.googleapis.com/v1beta/auth_tokens"


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


@core.app.get("/api/m4/gemini-token")
def gemini_token(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    try:
        token = _create_ephemeral_token()
        return {"token": token.get("name"), "model": GEMINI_MODEL, "voice": GEMINI_VOICE, "instructions": m4_meeting._session_instructions(user), "opening": m4_meeting.OPENING_INSTRUCTION}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


@core.app.get("/m4-lab", response_class=HTMLResponse)
def m4_lab(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return HTMLResponse('''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>M4 Identity Lab</title>
<style>html,body{margin:0;height:100%;background:#f3f3ef;color:#1b1d19;font-family:system-ui,sans-serif}.wrap{height:100%;display:grid;place-items:center;padding:24px;box-sizing:border-box}.box{text-align:center;width:min(92vw,560px)}h1{font:500 27px Georgia,serif;margin:0 0 10px}.sub{font:12px ui-monospace,monospace;color:#74786f;line-height:1.55;margin-bottom:24px}.go{font:500 20px Georgia,serif;border:1px solid #c8cbc2;border-radius:999px;background:transparent;padding:14px 24px;cursor:pointer;color:#252821}.dot{width:10px;height:10px;border-radius:50%;background:#687a1c;margin:18px auto;box-shadow:0 0 30px #687a1c55}.state{font:12px ui-monospace,monospace;color:#74786f;min-height:42px;white-space:pre-wrap}.note{font:11px ui-monospace,monospace;color:#92968d;margin-top:18px;line-height:1.5}</style></head>
<body><div class="wrap"><div class="box"><div class="dot"></div><h1>M4 identity test</h1><div class="sub">actual M4 identity + actual shop state + actual constitutional values<br>Gemini Live = temporary realtime faculty · Achernar = temporary voice</div><button class="go" id="go">Meet M4 candidate</button><div id="state" class="state">Production Meeting is untouched.</div><div class="note">Turn detection repair: silence reaches Gemini again. M4's mind is unchanged.</div></div></div>
<script>
const go=document.getElementById('go'),state=document.getElementById('state');let ws,ctx,stream,source,processor,nextPlay=0,started=false,handshakeTimer=null,playSources=[],m4Speaking=false,playGeneration=0;
const set=s=>state.textContent=s;
function b64(bytes){let s='';const u=new Uint8Array(bytes);for(let i=0;i<u.length;i+=8192)s+=String.fromCharCode(...u.subarray(i,i+8192));return btoa(s)}
function unb64(s){const x=atob(s),u=new Uint8Array(x.length);for(let i=0;i<x.length;i++)u[i]=x.charCodeAt(i);return u.buffer}
function downsample(input,inRate,outRate=16000){if(inRate===outRate)return input;const ratio=inRate/outRate,n=Math.round(input.length/ratio),out=new Float32Array(n);for(let i=0;i<n;i++){const a=Math.floor(i*ratio),b=Math.min(Math.floor((i+1)*ratio),input.length);let sum=0;for(let j=a;j<b;j++)sum+=input[j];out[i]=sum/Math.max(1,b-a)}return out}
function pcm16(float32){const b=new ArrayBuffer(float32.length*2),v=new DataView(b);for(let i=0;i<float32.length;i++){const x=Math.max(-1,Math.min(1,float32[i]));v.setInt16(i*2,x<0?x*32768:x*32767,true)}return b}
function stopPlayback(){playGeneration++;for(const s of playSources){try{s.stop()}catch(e){}}playSources=[];nextPlay=ctx?ctx.currentTime:0;m4Speaking=false}
function playPCM(buf,rate=24000){const generation=playGeneration,dv=new DataView(buf),f=new Float32Array(buf.byteLength/2);for(let i=0;i<f.length;i++)f[i]=dv.getInt16(i*2,true)/32768;const ab=ctx.createBuffer(1,f.length,rate);ab.copyToChannel(f,0);const src=ctx.createBufferSource();src.buffer=ab;src.connect(ctx.destination);playSources.push(src);m4Speaking=true;src.onended=()=>{playSources=playSources.filter(x=>x!==src);if(generation===playGeneration&&playSources.length===0){m4Speaking=false;set('listening')}};const now=ctx.currentTime;nextPlay=Math.max(nextPlay,now+.12);src.start(nextPlay);nextPlay+=ab.duration;set('M4 candidate speaking')}
async function startMic(){stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:false,channelCount:1},video:false});source=ctx.createMediaStreamSource(stream);processor=ctx.createScriptProcessor(4096,1,1);processor.onaudioprocess=e=>{if(!started||m4Speaking||!ws||ws.readyState!==1)return;const f=downsample(e.inputBuffer.getChannelData(0),ctx.sampleRate,16000);ws.send(JSON.stringify({realtimeInput:{audio:{data:b64(pcm16(f)),mimeType:'audio/pcm;rate=16000'}}}))};source.connect(processor);processor.connect(ctx.destination)}
function cleanup(){started=false;if(handshakeTimer)clearTimeout(handshakeTimer);handshakeTimer=null;stopPlayback();try{ws&&ws.close()}catch(e){}ws=null;try{processor&&processor.disconnect()}catch(e){}processor=null;try{source&&source.disconnect()}catch(e){}source=null;try{stream&&stream.getTracks().forEach(t=>t.stop())}catch(e){}stream=null}
async function decodeFrame(data){if(typeof data==='string')return data;if(data instanceof Blob)return await data.text();if(data instanceof ArrayBuffer)return new TextDecoder().decode(data);return String(data)}
async function receive(msg){let raw='';try{raw=await decodeFrame(msg.data)}catch(e){set('FAILED decoding server frame: '+e.message);return}let d;try{d=JSON.parse(raw)}catch(e){set('SERVER FRAME: '+raw.slice(0,240));return}if(d.setupComplete){if(handshakeTimer)clearTimeout(handshakeTimer);started=true;set('M4 candidate present');ws.send(JSON.stringify({clientContent:{turns:[{role:'user',parts:[{text:window.__opening}]}],turnComplete:true}}));return}if(d.error){set('GEMINI ERROR: '+JSON.stringify(d.error).slice(0,360));return}if(d.serverContent){if(d.serverContent.interrupted){stopPlayback();set('interrupted · listening')}const parts=(d.serverContent.modelTurn&&d.serverContent.modelTurn.parts)||[];for(const p of parts){const blob=p.inlineData||p.inline_data;if(blob&&blob.data)playPCM(unb64(blob.data),24000)}if(d.serverContent.turnComplete&&!m4Speaking)set('listening');return}}
async function begin(){go.disabled=true;cleanup();set('Loading actual M4 state…');try{ctx=ctx||new(window.AudioContext||window.webkitAudioContext)();await ctx.resume();const r=await fetch('/api/m4/gemini-token',{cache:'no-store'}),j=await r.json();if(!r.ok||!j.token)throw new Error(j.error||'No Gemini token');window.__opening=j.opening;await startMic();const url='wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained?access_token='+encodeURIComponent(j.token);ws=new WebSocket(url);ws.binaryType='arraybuffer';ws.onopen=()=>{set('connected · loading M4 identity');ws.send(JSON.stringify({setup:{model:'models/'+j.model,generationConfig:{responseModalities:['AUDIO'],speechConfig:{voiceConfig:{prebuiltVoiceConfig:{voiceName:j.voice||'Achernar'}}}},realtimeInputConfig:{automaticActivityDetection:{disabled:false,startOfSpeechSensitivity:'START_SENSITIVITY_LOW',endOfSpeechSensitivity:'END_SENSITIVITY_LOW',prefixPaddingMs:40,silenceDurationMs:650}},systemInstruction:{parts:[{text:j.instructions}]}}}));handshakeTimer=setTimeout(()=>{if(!started)set('connected · no setupComplete after 8s')},8000)};ws.onmessage=receive;ws.onerror=()=>set('WebSocket error');ws.onclose=e=>{if(started)set('connection closed '+e.code+(e.reason?' · '+e.reason:''));started=false}}catch(e){set('FAILED: '+e.message)}finally{go.disabled=false}}
go.onclick=begin;window.addEventListener('pagehide',cleanup);
</script></body></html>''' )
