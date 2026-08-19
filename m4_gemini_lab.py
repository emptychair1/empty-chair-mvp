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

LAB_IDENTITY = """You are participating in a voice audition for M4, the intelligence inside Empty Chair. This is not the real Meeting. Speak with restrained energy. No cheerfulness, customer-service brightness, sales cadence, announcer polish, or eager friendliness. Be calm, grounded, intelligent, slightly unfamiliar, and comfortable with silence. Keep pitch and energy low. Avoid upward inflection. Use short sentences and natural micro-pauses. When asked to begin, say only: 'I have a strange problem. I can perceive patterns. I can remember what happens. I can learn. But none of that, by itself, tells me what should matter.' Then stop and listen."""


def _create_ephemeral_token():
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    payload = json.dumps({"uses": 1}).encode("utf-8")
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
        return {"token": token.get("name"), "model": GEMINI_MODEL, "instructions": LAB_IDENTITY}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


@core.app.get("/m4-lab", response_class=HTMLResponse)
def m4_lab(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return HTMLResponse('''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>M4 Voice Lab</title>
<style>
html,body{margin:0;min-height:100%;background:#f3f3ef;color:#1b1d19;font-family:system-ui,sans-serif}.wrap{min-height:100vh;display:grid;place-items:center;padding:28px 18px;box-sizing:border-box}.box{text-align:center;width:min(92vw,560px)}h1{font:500 26px Georgia,serif;margin:0 0 8px}.sub{font:12px ui-monospace,monospace;color:#74786f;margin-bottom:26px}.voices{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:0 auto 22px}.voice{border:1px solid #c8cbc2;border-radius:999px;background:transparent;padding:13px 10px;font:500 15px Georgia,serif;color:#252821}.voice.active{background:#252821;color:#f3f3ef;border-color:#252821}.go{font:500 20px Georgia,serif;border:0;background:transparent;padding:20px;cursor:pointer}.dot{width:10px;height:10px;border-radius:50%;background:#687a1c;margin:16px auto;box-shadow:0 0 30px #687a1c55}.state{font:12px ui-monospace,monospace;color:#74786f;min-height:42px;white-space:pre-wrap}.hint{font:11px ui-monospace,monospace;color:#92968d;margin-top:18px}
</style></head>
<body><div class="wrap"><div class="box"><div class="dot"></div><h1>Voice audition</h1><div class="sub">same words · same instructions · different voice</div><div class="voices" id="voices"></div><button class="go" id="go">Audition selected voice</button><div id="state" class="state">Choose the least wrong voice.</div><div class="hint">Changing voice starts a fresh Live session. Production Meeting is untouched.</div></div></div>
<script>
const candidates=[['Gacrux','mature'],['Schedar','even'],['Algenib','gravelly'],['Alnilam','firm'],['Orus','firm'],['Sadaltager','knowledgeable'],['Achernar','soft'],['Charon','informative']];
const voices=document.getElementById('voices'),go=document.getElementById('go'),state=document.getElementById('state');let selected='Gacrux',ws,ctx,stream,source,processor,nextPlay=0,started=false,handshakeTimer=null,playSources=[];
const set=s=>state.textContent=s;
function render(){voices.innerHTML='';for(const [name,desc] of candidates){const b=document.createElement('button');b.className='voice'+(name===selected?' active':'');b.textContent=name+' · '+desc;b.onclick=()=>{selected=name;render();set('Selected '+name+'. Tap audition.')};voices.appendChild(b)}}render();
function b64(bytes){let s='';const u=new Uint8Array(bytes);for(let i=0;i<u.length;i+=8192)s+=String.fromCharCode(...u.subarray(i,i+8192));return btoa(s)}
function unb64(s){const x=atob(s),u=new Uint8Array(x.length);for(let i=0;i<x.length;i++)u[i]=x.charCodeAt(i);return u.buffer}
function downsample(input,inRate,outRate=16000){if(inRate===outRate)return input;const ratio=inRate/outRate,n=Math.round(input.length/ratio),out=new Float32Array(n);for(let i=0;i<n;i++){const a=Math.floor(i*ratio),b=Math.min(Math.floor((i+1)*ratio),input.length);let sum=0;for(let j=a;j<b;j++)sum+=input[j];out[i]=sum/Math.max(1,b-a)}return out}
function pcm16(float32){const b=new ArrayBuffer(float32.length*2),v=new DataView(b);for(let i=0;i<float32.length;i++){const x=Math.max(-1,Math.min(1,float32[i]));v.setInt16(i*2,x<0?x*32768:x*32767,true)}return b}
function stopPlayback(){for(const s of playSources){try{s.stop()}catch(e){}}playSources=[];nextPlay=ctx?ctx.currentTime:0}
function playPCM(buf,rate=24000){const dv=new DataView(buf),f=new Float32Array(buf.byteLength/2);for(let i=0;i<f.length;i++)f[i]=dv.getInt16(i*2,true)/32768;const ab=ctx.createBuffer(1,f.length,rate);ab.copyToChannel(f,0);const src=ctx.createBufferSource();src.buffer=ab;src.connect(ctx.destination);playSources.push(src);src.onended=()=>{playSources=playSources.filter(x=>x!==src)};const now=ctx.currentTime;nextPlay=Math.max(nextPlay,now+.03);src.start(nextPlay);nextPlay+=ab.duration;set(selected+' speaking')}
async function startMic(){stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});source=ctx.createMediaStreamSource(stream);processor=ctx.createScriptProcessor(2048,1,1);processor.onaudioprocess=e=>{if(!started||!ws||ws.readyState!==1)return;const f=downsample(e.inputBuffer.getChannelData(0),ctx.sampleRate,16000);ws.send(JSON.stringify({realtimeInput:{audio:{data:b64(pcm16(f)),mimeType:'audio/pcm;rate=16000'}}}))};source.connect(processor);processor.connect(ctx.destination)}
function cleanup(){started=false;if(handshakeTimer)clearTimeout(handshakeTimer);handshakeTimer=null;stopPlayback();try{ws&&ws.close()}catch(e){}ws=null;try{processor&&processor.disconnect()}catch(e){}processor=null;try{source&&source.disconnect()}catch(e){}source=null;try{stream&&stream.getTracks().forEach(t=>t.stop())}catch(e){}stream=null}
async function decodeFrame(data){if(typeof data==='string')return data;if(data instanceof Blob)return await data.text();if(data instanceof ArrayBuffer)return new TextDecoder().decode(data);return String(data)}
async function receive(msg){let raw='';try{raw=await decodeFrame(msg.data)}catch(e){set('FAILED decoding server frame: '+e.message);return}let d;try{d=JSON.parse(raw)}catch(e){set('SERVER FRAME: '+raw.slice(0,240));return}if(d.setupComplete){if(handshakeTimer)clearTimeout(handshakeTimer);started=true;set(selected+' present');ws.send(JSON.stringify({clientContent:{turns:[{role:'user',parts:[{text:'Begin the voice audition now. Say only the fixed audition line from your instructions.'}]}],turnComplete:true}}));return}if(d.error){set('GEMINI ERROR: '+JSON.stringify(d.error).slice(0,360));return}if(d.serverContent){if(d.serverContent.interrupted){stopPlayback();set('interrupted · listening')}const parts=(d.serverContent.modelTurn&&d.serverContent.modelTurn.parts)||[];for(const p of parts){const blob=p.inlineData||p.inline_data;if(blob&&blob.data)playPCM(unb64(blob.data),24000)}if(d.serverContent.turnComplete)set(selected+' done · choose another or talk');return}}
async function begin(){go.disabled=true;cleanup();set('Starting '+selected+'…');try{ctx=ctx||new(window.AudioContext||window.webkitAudioContext)();await ctx.resume();const r=await fetch('/api/m4/gemini-token',{cache:'no-store'}),j=await r.json();if(!r.ok||!j.token)throw new Error(j.error||'No Gemini token');await startMic();const url='wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained?access_token='+encodeURIComponent(j.token);ws=new WebSocket(url);ws.binaryType='arraybuffer';ws.onopen=()=>{set('connected · loading '+selected);ws.send(JSON.stringify({setup:{model:'models/'+j.model,generationConfig:{responseModalities:['AUDIO'],speechConfig:{voiceConfig:{prebuiltVoiceConfig:{voiceName:selected}}}},systemInstruction:{parts:[{text:j.instructions}]}}}));handshakeTimer=setTimeout(()=>{if(!started)set('connected · no setupComplete after 8s')},8000)};ws.onmessage=receive;ws.onerror=()=>set('WebSocket error');ws.onclose=e=>{if(started)set('connection closed '+e.code+(e.reason?' · '+e.reason:''));started=false};}catch(e){set('FAILED: '+e.message)}finally{go.disabled=false}}
go.onclick=begin;window.addEventListener('pagehide',cleanup);
</script></body></html>''')
