"""Low-latency Gemini prospect Meeting transport.

The sales experience prioritizes conversational responsiveness. Incoming Gemini PCM
starts as soon as a small anti-jitter cushion exists; audio is then continuously
scheduled ahead. There is no artificial 'thinking' delay.
"""
from fastapi import Request
from fastapi.responses import HTMLResponse
import app as core

@core.app.get("/m4-smooth", response_class=HTMLResponse)
def m4_smooth(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return HTMLResponse(r'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>The Meeting</title>
<style>html,body{margin:0;height:100%;background:#f3f3ef;color:#1b1d19;font-family:system-ui,sans-serif}.wrap{height:100%;display:grid;place-items:center;padding:24px;box-sizing:border-box}.box{text-align:center;width:min(92vw,560px)}h1{font:500 28px Georgia,serif;margin:0 0 10px}.sub,.state{font:12px ui-monospace,monospace;color:#74786f;line-height:1.55}.sub{margin-bottom:24px}.go{font:500 20px Georgia,serif;border:1px solid #c8cbc2;border-radius:999px;background:transparent;padding:14px 24px;cursor:pointer;color:#252821}.dot{width:10px;height:10px;border-radius:50%;background:#687a1c;margin:18px auto}.state{min-height:42px}</style></head>
<body><div class="wrap"><div class="box"><div class="dot"></div><h1>The Meeting</h1><div class="sub">with M4</div><button class="go" id="go">Enter</button><div id="state" class="state">ready</div></div></div>
<script>
const go=document.getElementById('go'),state=document.getElementById('state');
let ws,ctx,stream,source,processor,started=false,userSpeaking=false,lastVoiceAt=0,voiceStartedAt=0;
let pcmQueue=[],queuedSamples=0,playbackStarted=false,nextPlayTime=0,activeSources=new Set(),turnComplete=false;
const PLAY_RATE=24000,START_BUFFER_SAMPLES=Math.round(PLAY_RATE*.22),MIN_LEAD=.09,TARGET_LEAD=.16;
const set=s=>state.textContent=s;
function b64(bytes){let s='';const u=new Uint8Array(bytes);for(let i=0;i<u.length;i+=8192)s+=String.fromCharCode(...u.subarray(i,i+8192));return btoa(s)}
function unb64(s){const x=atob(s),u=new Uint8Array(x.length);for(let i=0;i<x.length;i++)u[i]=x.charCodeAt(i);return u}
function downsample(input,inRate,outRate=16000){if(inRate===outRate)return input;const ratio=inRate/outRate,n=Math.round(input.length/ratio),out=new Float32Array(n);for(let i=0;i<n;i++){const a=Math.floor(i*ratio),b=Math.min(Math.floor((i+1)*ratio),input.length);let sum=0;for(let j=a;j<b;j++)sum+=input[j];out[i]=sum/Math.max(1,b-a)}return out}
function pcm16(f){const b=new ArrayBuffer(f.length*2),v=new DataView(b);for(let i=0;i<f.length;i++){const x=Math.max(-1,Math.min(1,f[i]));v.setInt16(i*2,x<0?x*32768:x*32767,true)}return b}
function send(o){if(ws&&ws.readyState===1)ws.send(JSON.stringify(o))}
function beginUserTurn(){if(userSpeaking)return;userSpeaking=true;voiceStartedAt=performance.now();send({realtimeInput:{activityStart:{}}});set('listening')}
function endUserTurn(){if(!userSpeaking)return;userSpeaking=false;send({realtimeInput:{activityEnd:{}}});set('with you')}
function clearPlayback(){for(const s of activeSources){try{s.stop()}catch(_){}}activeSources.clear();pcmQueue=[];queuedSamples=0;playbackStarted=false;nextPlayTime=0;turnComplete=false}
function pcmToFloat(c){const n=Math.floor(c.byteLength/2),f=new Float32Array(n),dv=new DataView(c.buffer,c.byteOffset,c.byteLength);for(let i=0;i<n;i++)f[i]=dv.getInt16(i*2,true)/32768;return f}
function scheduleChunk(c){const f=pcmToFloat(c),b=ctx.createBuffer(1,f.length,PLAY_RATE);b.copyToChannel(f,0);const src=ctx.createBufferSource();src.buffer=b;src.connect(ctx.destination);const now=ctx.currentTime,startAt=Math.max(nextPlayTime||0,now+MIN_LEAD);src.start(startAt);nextPlayTime=startAt+b.duration;activeSources.add(src);src.onended=()=>{activeSources.delete(src);if(turnComplete&&activeSources.size===0&&pcmQueue.length===0){playbackStarted=false;nextPlayTime=0;turnComplete=false;set('listening')}}}
function pump(force=false){if(!ctx)return;if(!playbackStarted){if(!force&&queuedSamples<START_BUFFER_SAMPLES)return;playbackStarted=true;set('speaking');nextPlayTime=Math.max(ctx.currentTime+TARGET_LEAD,nextPlayTime||0)}while(pcmQueue.length){const c=pcmQueue.shift();queuedSamples-=Math.floor(c.byteLength/2);scheduleChunk(c)}}
function enqueue(c){pcmQueue.push(c);queuedSamples+=Math.floor(c.byteLength/2);pump(false)}
async function startMic(){stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:false,channelCount:1},video:false});source=ctx.createMediaStreamSource(stream);processor=ctx.createScriptProcessor(1024,1,1);processor.onaudioprocess=e=>{if(!started||playbackStarted||activeSources.size||!ws||ws.readyState!==1)return;const f=downsample(e.inputBuffer.getChannelData(0),ctx.sampleRate,16000);let energy=0;for(let i=0;i<f.length;i++)energy+=f[i]*f[i];const rms=Math.sqrt(energy/Math.max(1,f.length)),now=performance.now();if(rms>=.018){lastVoiceAt=now;beginUserTurn()}if(userSpeaking){send({realtimeInput:{audio:{data:b64(pcm16(f)),mimeType:'audio/pcm;rate=16000'}}});if(now-lastVoiceAt>620&&now-voiceStartedAt>250)endUserTurn()}};source.connect(processor);processor.connect(ctx.destination)}
function cleanup(){started=false;userSpeaking=false;clearPlayback();try{ws&&ws.close()}catch(_){}ws=null;try{processor&&processor.disconnect()}catch(_){}processor=null;try{source&&source.disconnect()}catch(_){}source=null;try{stream&&stream.getTracks().forEach(t=>t.stop())}catch(_){}stream=null}
async function decodeFrame(data){if(typeof data==='string')return data;if(data instanceof Blob)return await data.text();if(data instanceof ArrayBuffer)return new TextDecoder().decode(data);return String(data)}
async function receive(msg){let d;try{d=JSON.parse(await decodeFrame(msg.data))}catch(e){set('connection data error');return}if(d.setupComplete){started=true;set('present');send({clientContent:{turns:[{role:'user',parts:[{text:window.__opening}]}],turnComplete:true}});return}if(d.error){set('connection error');return}if(!d.serverContent)return;const sc=d.serverContent;if(sc.interrupted){clearPlayback();set('listening')}const parts=(sc.modelTurn&&sc.modelTurn.parts)||[];for(const p of parts){const blob=p.inlineData||p.inline_data;if(blob&&blob.data)enqueue(unb64(blob.data))}if(sc.turnComplete){turnComplete=true;pump(true);if(activeSources.size===0&&pcmQueue.length===0){playbackStarted=false;nextPlayTime=0;turnComplete=false;set('listening')}}}
async function begin(){go.disabled=true;cleanup();set('connecting');try{ctx=ctx||new(window.AudioContext||window.webkitAudioContext)();await ctx.resume();const r=await fetch('/api/m4/gemini-token?guest=prospect',{cache:'no-store'}),j=await r.json();if(!r.ok||!j.token)throw new Error(j.error||'No Gemini token');window.__opening=j.opening;await startMic();ws=new WebSocket('wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained?access_token='+encodeURIComponent(j.token));ws.binaryType='arraybuffer';ws.onopen=()=>send({setup:{model:'models/'+j.model,generationConfig:{responseModalities:['AUDIO'],speechConfig:{voiceConfig:{prebuiltVoiceConfig:{voiceName:j.voice||'Achernar'}}}},realtimeInputConfig:{automaticActivityDetection:{disabled:true}},inputAudioTranscription:{},outputAudioTranscription:{},systemInstruction:{parts:[{text:j.instructions+'\n\nREALTIME CONVERSATION: Responsiveness is essential. Answer promptly once the person finishes speaking. Prefer an immediate concise first sentence over silently composing a long answer. Keep most turns to one or two short sentences, then let the person respond. Do not narrate thinking, say you are thinking, or use empty filler to hide latency. If deeper reasoning is useful, begin with the part you already know and develop the thought conversationally.'}]}}});ws.onmessage=receive;ws.onerror=()=>set('connection error');ws.onclose=()=>{started=false;set('connection closed')}}catch(e){set('FAILED: '+e.message)}finally{go.disabled=false}}
go.onclick=begin;window.addEventListener('pagehide',cleanup);
</script></body></html>''')
