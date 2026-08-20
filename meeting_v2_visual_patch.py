"""Final presentation layer for The Meeting v2.

A real tattoo-shop back room, one living cellular M4 presence, minimal UI, and
local ambience. This module does not alter voice, reasoning, persistence, or
Meeting endpoints.
"""
from pathlib import Path

from fastapi.responses import FileResponse

import app as core

_ASSET_DIR = Path(__file__).resolve().parent / "static" / "m4"


@core.app.get("/m4-assets/room-mobile.webp")
def m4_room_mobile():
    return FileResponse(_ASSET_DIR / "room-mobile.webp", media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@core.app.get("/m4-assets/room-desktop.webp")
def m4_room_desktop():
    return FileResponse(_ASSET_DIR / "room-desktop.webp", media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


VISUAL_CSS = r'''
<style id="m4-presentation-final">
html,body{background:#090907!important}
.room{
  background-image:linear-gradient(180deg,rgba(5,5,4,.12),rgba(5,5,4,.02) 50%,rgba(5,5,4,.28)),url('/m4-assets/room-mobile.webp')!important;
  background-size:cover!important;background-position:50% 47%!important;background-repeat:no-repeat!important;perspective:1200px!important
}
.room:before{content:''!important;position:absolute!important;inset:0!important;pointer-events:none!important;background:radial-gradient(ellipse at 50% 43%,transparent 0 35%,rgba(0,0,0,.06) 58%,rgba(0,0,0,.42) 100%)!important;filter:none!important;opacity:1!important;z-index:1!important}
.room:after{content:''!important;position:absolute!important;inset:0!important;pointer-events:none!important;background:linear-gradient(180deg,rgba(0,0,0,.18),transparent 18% 73%,rgba(0,0,0,.32))!important;filter:none!important;opacity:1!important;z-index:1!important}
.grain{opacity:.012!important}.chamber-depth,.light-column,.signal-field,.ambient-label{display:none!important}
.presence{width:min(66vw,390px)!important;height:min(66vw,390px)!important;position:relative!important;z-index:3!important;transform:translateY(-2vh) scale(.98)!important;filter:drop-shadow(0 30px 26px rgba(0,0,0,.52)) drop-shadow(0 0 26px rgba(250,212,153,.14))!important;transition:transform .9s cubic-bezier(.2,.7,.2,1),filter .9s ease!important}
.presence:before{content:''!important;position:absolute!important;left:15%!important;right:15%!important;bottom:-9%!important;height:17%!important;border:0!important;border-radius:50%!important;background:radial-gradient(ellipse,rgba(0,0,0,.48),rgba(0,0,0,0) 70%)!important;filter:blur(11px)!important;opacity:.72!important;transform:scaleX(1.08)!important;animation:none!important;box-shadow:none!important}
.presence:after{display:none!important}.presence svg{width:100%!important;height:100%!important;filter:contrast(1.02) saturate(.88)!important;opacity:.96!important}
.presence .membrane{animation:m4alive 9.2s ease-in-out infinite!important;transform-origin:50% 50%!important}.presence .inner{animation:m4inner 13s ease-in-out infinite!important;transform-origin:50% 50%!important}
@keyframes m4alive{0%,100%{transform:scale(.985) rotate(-.45deg)}35%{transform:scale(1.018,1.006) rotate(.35deg)}68%{transform:scale(.993,1.022) rotate(-.18deg)}}
@keyframes m4inner{0%,100%{transform:scale(.97) rotate(0);opacity:.72}50%{transform:scale(1.045) rotate(2.4deg);opacity:.94}}
.presence.listening{transform:translateY(-2.5vh) scale(1.035)!important;filter:drop-shadow(0 32px 28px rgba(0,0,0,.5)) drop-shadow(0 0 34px rgba(255,220,164,.2))!important}.presence.listening .membrane{animation-duration:5.8s!important}.presence.listening .inner{animation-duration:7s!important}
.presence.thinking{transform:translateY(-1.5vh) scale(.965)!important}.presence.thinking .membrane{animation-duration:7.8s!important}.presence.thinking .inner{animation-duration:4.4s!important}
.presence.speaking{transform:translateY(-2.5vh) scale(1.015)!important;filter:drop-shadow(0 34px 29px rgba(0,0,0,.52)) drop-shadow(0 0 40px rgba(255,218,155,.24))!important}.presence.speaking .membrane{animation-duration:2.7s!important}.presence.speaking .inner{animation-duration:2.15s!important}
.status{bottom:max(23px,calc(env(safe-area-inset-bottom) + 14px))!important;width:auto!important;min-width:0!important;max-width:min(76vw,390px)!important;padding:7px 12px 8px!important;border:1px solid rgba(255,255,255,.11)!important;border-radius:18px!important;background:rgba(8,7,6,.30)!important;backdrop-filter:blur(12px)!important;-webkit-backdrop-filter:blur(12px)!important;box-shadow:0 8px 30px rgba(0,0,0,.13)!important}
.state{font-size:8px!important;letter-spacing:.22em!important;color:rgba(255,255,255,.68)!important}.hint{font-size:11px!important;line-height:1.3!important;margin-top:4px!important;color:rgba(255,255,255,.72)!important}
.controls{z-index:6!important;top:max(15px,env(safe-area-inset-top))!important;right:15px!important;gap:8px!important}.control{width:42px!important;height:42px!important;background:rgba(7,7,6,.32)!important;border:1px solid rgba(255,255,255,.14)!important;color:rgba(255,255,255,.78)!important;backdrop-filter:blur(10px)!important;-webkit-backdrop-filter:blur(10px)!important}
.enter{background:rgba(7,7,6,.42)!important;backdrop-filter:blur(5px)!important;-webkit-backdrop-filter:blur(5px)!important}.enter button{color:#f2eee5!important;background:rgba(12,11,9,.58)!important;border-color:rgba(255,255,255,.18)!important;box-shadow:0 18px 50px rgba(0,0,0,.30)!important}
@media(min-width:760px){.room{background-image:linear-gradient(180deg,rgba(5,5,4,.10),rgba(5,5,4,.01) 52%,rgba(5,5,4,.22)),url('/m4-assets/room-desktop.webp')!important;background-position:center center!important}.presence{width:min(39vw,520px)!important;height:min(39vw,520px)!important;transform:translateY(-1vh) scale(.98)!important}.presence.listening{transform:translateY(-1.4vh) scale(1.035)!important}.presence.thinking{transform:translateY(-.6vh) scale(.965)!important}.presence.speaking{transform:translateY(-1.4vh) scale(1.015)!important}.status{bottom:28px!important}}
@media(max-width:420px){.presence{width:69vw!important;height:69vw!important}.status{max-width:72vw!important}}
</style>
'''

VISUAL_JS = r'''
<script id="m4-depth-ambience-final">
(function(){
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
