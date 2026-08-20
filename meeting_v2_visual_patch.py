"""Final presentation layer for The Meeting v2.

A real tattoo-shop back room, one image-based living cellular M4 presence,
minimal UI, and local ambience. Voice, reasoning, persistence, and Meeting
endpoints remain untouched.
"""
from pathlib import Path

from fastapi.responses import FileResponse

import app as core

_ASSET_DIR = Path(__file__).resolve().parent / "static" / "m4"
_M4_DIR = Path(__file__).resolve().parent / "m4_assets"


def _asset(name: str) -> str:
    try:
        raw = (_M4_DIR / name).read_text(encoding="utf-8").strip()
        return "data:image/webp;base64," + raw
    except Exception:
        return ""

M4_CELL = _asset("present.b64")


@core.app.get("/m4-assets/room-mobile.webp")
def m4_room_mobile():
    return FileResponse(_ASSET_DIR / "room-mobile.webp", media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@core.app.get("/m4-assets/room-desktop.webp")
def m4_room_desktop():
    return FileResponse(_ASSET_DIR / "room-desktop.webp", media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


VISUAL_CSS = r'''
<style id="m4-presentation-final">
html,body{background:#090907!important}
.room{background-image:linear-gradient(180deg,rgba(5,5,4,.10),rgba(5,5,4,.01) 50%,rgba(5,5,4,.25)),url('/m4-assets/room-mobile.webp')!important;background-size:cover!important;background-position:50% 47%!important;background-repeat:no-repeat!important;perspective:1200px!important}
.room:before{content:''!important;position:absolute!important;inset:0!important;pointer-events:none!important;background:radial-gradient(ellipse at 50% 44%,transparent 0 38%,rgba(0,0,0,.04) 62%,rgba(0,0,0,.38) 100%)!important;filter:none!important;opacity:1!important;z-index:1!important}
.room:after{content:''!important;position:absolute!important;inset:0!important;pointer-events:none!important;background:linear-gradient(180deg,rgba(0,0,0,.16),transparent 18% 74%,rgba(0,0,0,.29))!important;filter:none!important;opacity:1!important;z-index:1!important}
.grain{opacity:.01!important}.chamber-depth,.light-column,.signal-field,.ambient-label{display:none!important}
.presence{position:relative!important;z-index:3!important;width:min(66vw,390px)!important;height:min(66vw,390px)!important;display:block!important;transform:translateY(-2vh) scale(.98)!important;transform-origin:50% 50%!important;filter:drop-shadow(0 29px 27px rgba(0,0,0,.55)) drop-shadow(0 0 25px rgba(255,206,137,.13))!important;transition:transform .9s cubic-bezier(.2,.7,.2,1),filter .8s ease!important}
.presence svg{display:none!important}
.presence:before{content:''!important;display:block!important;position:absolute!important;inset:0!important;border:0!important;border-radius:44% 56% 48% 52%/52% 47% 53% 48%!important;background-image:url("__M4_CELL__")!important;background-size:contain!important;background-position:center!important;background-repeat:no-repeat!important;box-shadow:none!important;opacity:.94!important;animation:m4Idle 8.6s ease-in-out infinite!important;filter:brightness(.92) saturate(.74) contrast(1.03)!important;will-change:transform,filter,opacity!important}
.presence:after{content:''!important;display:block!important;position:absolute!important;left:14%!important;right:14%!important;bottom:-8%!important;height:15%!important;border:0!important;border-radius:50%!important;background:radial-gradient(ellipse,rgba(0,0,0,.48),rgba(0,0,0,0) 72%)!important;filter:blur(10px)!important;opacity:.72!important;animation:none!important;box-shadow:none!important;pointer-events:none!important}
@keyframes m4Idle{0%,100%{transform:scale(.966) rotate(-.45deg) skewX(-.25deg)}35%{transform:scale(1.008,1.002) rotate(.28deg) skewX(.18deg)}68%{transform:scale(.985,1.014) rotate(-.12deg) skewY(.18deg)}}
@keyframes m4Listen{0%,100%{transform:scale(1.002) rotate(-.18deg)}50%{transform:scale(1.048) rotate(.28deg)}}
@keyframes m4Think{0%,100%{transform:scale(.935) rotate(-.65deg) skewX(-.32deg)}50%{transform:scale(.976) rotate(.48deg) skewY(.24deg)}}
@keyframes m4Speak{0%,100%{transform:scale(.994) rotate(-.12deg)}45%{transform:scale(1.05) rotate(.2deg)}72%{transform:scale(1.015) rotate(-.14deg)}}
.presence.listening{transform:translateY(-2.5vh) scale(1.025)!important;filter:drop-shadow(0 31px 28px rgba(0,0,0,.53)) drop-shadow(0 0 34px rgba(255,215,154,.20))!important}.presence.listening:before{animation:m4Listen 3.7s ease-in-out infinite!important;filter:brightness(1.04) saturate(.82) contrast(1.03)!important}
.presence.thinking{transform:translateY(-1.5vh) scale(.97)!important}.presence.thinking:before{animation:m4Think 3.1s ease-in-out infinite!important;filter:brightness(.84) saturate(.68) contrast(1.06)!important}
.presence.speaking{transform:translateY(-2.5vh) scale(1.012)!important;filter:drop-shadow(0 32px 29px rgba(0,0,0,.54)) drop-shadow(0 0 39px rgba(255,216,157,.23))!important}.presence.speaking:before{animation:m4Speak 1.55s ease-in-out infinite!important;filter:brightness(1.12) saturate(.88) contrast(1.04)!important}
.m4-vesicle{position:absolute;z-index:4;width:4px;height:4px;border-radius:50%;background:rgba(255,231,196,.55);box-shadow:0 0 9px rgba(255,193,112,.42);pointer-events:none;opacity:.18}.m4-v1{left:24%;top:33%;animation:v1 11s ease-in-out infinite}.m4-v2{right:23%;top:27%;width:3px;height:3px;animation:v2 9s ease-in-out infinite}.m4-v3{right:20%;bottom:31%;width:3px;height:3px;animation:v3 12s ease-in-out infinite}
@keyframes v1{0%,100%{transform:translate(0,0);opacity:.10}50%{transform:translate(12px,-15px);opacity:.34}}@keyframes v2{0%,100%{transform:translate(0,0);opacity:.10}55%{transform:translate(-10px,14px);opacity:.32}}@keyframes v3{0%,100%{transform:translate(0,0);opacity:.08}50%{transform:translate(-14px,-8px);opacity:.30}}
.status{bottom:max(22px,calc(env(safe-area-inset-bottom) + 13px))!important;width:auto!important;min-width:0!important;max-width:min(74vw,370px)!important;padding:6px 11px 7px!important;border:1px solid rgba(255,255,255,.10)!important;border-radius:16px!important;background:rgba(8,7,6,.27)!important;backdrop-filter:blur(10px)!important;-webkit-backdrop-filter:blur(10px)!important;box-shadow:0 8px 28px rgba(0,0,0,.12)!important}.state{min-height:8px!important;font-size:8px!important;letter-spacing:.22em!important;color:rgba(255,255,255,.65)!important}.hint{margin-top:3px!important;font:400 10px/1.3 Georgia,serif!important;color:rgba(255,247,234,.70)!important}
.controls{z-index:6!important;top:max(14px,env(safe-area-inset-top))!important;right:13px!important;gap:8px!important}.control{width:39px!important;height:39px!important;border-color:rgba(255,255,255,.12)!important;background:rgba(7,6,5,.27)!important;color:rgba(255,244,228,.72)!important;backdrop-filter:blur(9px)!important;-webkit-backdrop-filter:blur(9px)!important}.enter{background:rgba(7,6,5,.30)!important;backdrop-filter:blur(3px)!important;-webkit-backdrop-filter:blur(3px)!important}.enter button{border-color:rgba(255,255,255,.17)!important;background:rgba(8,7,6,.54)!important;color:#f6eee3!important;box-shadow:0 16px 55px rgba(0,0,0,.32)!important}
@media(min-width:760px){.room{background-image:linear-gradient(180deg,rgba(5,5,4,.08),rgba(5,5,4,.01) 52%,rgba(5,5,4,.20)),url('/m4-assets/room-desktop.webp')!important;background-position:center center!important}.presence{width:min(39vw,510px)!important;height:min(39vw,510px)!important;transform:translateY(-1vh) scale(.98)!important}.presence.listening{transform:translateY(-1.4vh) scale(1.025)!important}.presence.thinking{transform:translateY(-.6vh) scale(.97)!important}.presence.speaking{transform:translateY(-1.4vh) scale(1.012)!important}.status{bottom:27px!important}}
@media(max-width:420px){.presence{width:68vw!important;height:68vw!important}.status{max-width:71vw!important}}
</style>
'''.replace("__M4_CELL__", M4_CELL)

VISUAL_JS = r'''
<script id="m4-life-final">
(function(){
 const p=document.getElementById('presence');if(p&&!p.querySelector('.m4-vesicle')){['m4-v1','m4-v2','m4-v3'].forEach(c=>{const i=document.createElement('i');i.className='m4-vesicle '+c;p.appendChild(i)})}
 let built=false,noise=null,hum=null,noiseGain=null,humGain=null,pulseTimer=null;
 function build(){if(built||!window.audioCtx||!window.master)return;built=true;const ctx=window.audioCtx;try{const buf=ctx.createBuffer(1,ctx.sampleRate*2,ctx.sampleRate),d=buf.getChannelData(0);let last=0;for(let i=0;i<d.length;i++){const w=Math.random()*2-1;last=last*.992+w*.008;d[i]=last*.24}noise=ctx.createBufferSource();noise.buffer=buf;noise.loop=true;const lp=ctx.createBiquadFilter();lp.type='lowpass';lp.frequency.value=190;noiseGain=ctx.createGain();noiseGain.gain.value=.025;noise.connect(lp).connect(noiseGain).connect(window.master);noise.start();hum=ctx.createOscillator();hum.type='sine';hum.frequency.value=37;humGain=ctx.createGain();humGain.gain.value=.035;hum.connect(humGain).connect(window.master);hum.start();const pulse=()=>{if(!humGain)return;const t=ctx.currentTime;humGain.gain.cancelScheduledValues(t);humGain.gain.setValueAtTime(.03,t);humGain.gain.linearRampToValueAtTime(.052,t+1.7);humGain.gain.linearRampToValueAtTime(.03,t+4.6)};pulse();pulseTimer=setInterval(pulse,5200)}catch(e){console.log('M4 room ambience unavailable',e)}}
 const oldAmbient=window.ambient;if(typeof oldAmbient==='function')window.ambient=function(){oldAmbient();try{if(window.master)window.master.gain.value=.16;build()}catch(e){}};
})();
</script>
'''


def enhance(html: str) -> str:
    if 'id="m4-presentation-final"' in html:
        return html
    html = html.replace("</head>", VISUAL_CSS + "</head>")
    html = html.replace("</body>", VISUAL_JS + "</body>")
    return html
