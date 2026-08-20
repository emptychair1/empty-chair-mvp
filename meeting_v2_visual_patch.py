"""Presentation layer for The Meeting v2.

Keeps the tattoo-shop room and replaces the image-based M4 body with a subtle,
state-reactive CSS glow using the product's restrained lime-green signal color.
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
<style id="m4-presentation-green">
:root{--m4-green:#b7f34a;--m4-green-soft:rgba(183,243,74,.42);--m4-green-faint:rgba(183,243,74,.12)}
html,body{background:#090907!important}
.room{background-image:linear-gradient(180deg,rgba(5,5,4,.07),rgba(5,5,4,.01) 52%,rgba(5,5,4,.18)),url('/m4-assets/room-mobile.webp')!important;background-size:cover!important;background-position:50% 45%!important;background-repeat:no-repeat!important;perspective:1200px!important}
.room:before{content:''!important;position:absolute!important;inset:0!important;pointer-events:none!important;background:radial-gradient(ellipse at 50% 44%,transparent 0 43%,rgba(0,0,0,.03) 67%,rgba(0,0,0,.25) 100%)!important;filter:none!important;opacity:1!important;z-index:1!important}
.room:after{content:''!important;position:absolute!important;inset:0!important;pointer-events:none!important;background:linear-gradient(180deg,rgba(0,0,0,.08),transparent 22% 79%,rgba(0,0,0,.19))!important;filter:none!important;opacity:1!important;z-index:1!important}
.grain{opacity:.008!important}.chamber-depth,.light-column,.signal-field,.ambient-label,.m4-vesicle{display:none!important}
.presence{position:relative!important;z-index:3!important;width:min(42vw,220px)!important;height:min(42vw,220px)!important;display:block!important;transform:translateY(-3vh)!important;transform-origin:50% 50%!important;filter:none!important;transition:transform .8s cubic-bezier(.2,.7,.2,1)!important}
.presence svg{display:none!important}
.presence:before{content:''!important;position:absolute!important;inset:23%!important;border-radius:50%!important;background:radial-gradient(circle at 46% 44%,rgba(239,255,212,.82) 0 3%,rgba(201,255,116,.65) 4% 11%,rgba(183,243,74,.34) 18% 31%,rgba(183,243,74,.12) 48%,rgba(183,243,74,0) 72%)!important;box-shadow:0 0 18px rgba(183,243,74,.25),0 0 46px rgba(183,243,74,.18),0 0 92px rgba(183,243,74,.09)!important;filter:blur(.2px)!important;opacity:.78!important;animation:m4Breathe 6.8s ease-in-out infinite!important;will-change:transform,opacity,filter,box-shadow!important}
.presence:after{content:''!important;position:absolute!important;inset:8%!important;border-radius:50%!important;background:radial-gradient(circle,rgba(183,243,74,.06),rgba(183,243,74,.025) 37%,rgba(183,243,74,0) 70%)!important;filter:blur(10px)!important;opacity:.58!important;animation:m4Halo 9.5s ease-in-out infinite!important;box-shadow:none!important}
@keyframes m4Breathe{0%,100%{transform:scale(.88);opacity:.56;filter:blur(.45px)}50%{transform:scale(1.06);opacity:.82;filter:blur(0)}}
@keyframes m4Halo{0%,100%{transform:scale(.88);opacity:.34}50%{transform:scale(1.13);opacity:.64}}
@keyframes m4Listen{0%,100%{transform:scale(.98);opacity:.78}50%{transform:scale(1.16);opacity:1}}
@keyframes m4Think{0%,100%{transform:scale(.80);opacity:.55}50%{transform:scale(.91);opacity:.72}}
@keyframes m4Speak{0%,100%{transform:scale(.94);opacity:.78}35%{transform:scale(1.10);opacity:1}68%{transform:scale(1.01);opacity:.88}}
.presence.listening{transform:translateY(-3vh) scale(1.06)!important}.presence.listening:before{animation:m4Listen 2.9s ease-in-out infinite!important;box-shadow:0 0 22px rgba(183,243,74,.34),0 0 60px rgba(183,243,74,.24),0 0 120px rgba(183,243,74,.12)!important}.presence.listening:after{opacity:.72!important}
.presence.thinking{transform:translateY(-2.5vh) scale(.94)!important}.presence.thinking:before{animation:m4Think 2.4s ease-in-out infinite!important;box-shadow:0 0 14px rgba(183,243,74,.22),0 0 38px rgba(183,243,74,.14)!important}.presence.thinking:after{opacity:.36!important}
.presence.speaking{transform:translateY(-3vh) scale(1.02)!important}.presence.speaking:before{animation:m4Speak 1.15s ease-in-out infinite!important;box-shadow:0 0 24px rgba(183,243,74,.40),0 0 68px rgba(183,243,74,.27),0 0 130px rgba(183,243,74,.14)!important}.presence.speaking:after{animation-duration:3.2s!important;opacity:.75!important}
.status{bottom:max(20px,calc(env(safe-area-inset-bottom) + 12px))!important;width:auto!important;min-width:0!important;max-width:min(72vw,350px)!important;padding:5px 10px 6px!important;border:1px solid rgba(255,255,255,.08)!important;border-radius:14px!important;background:rgba(8,7,6,.20)!important;backdrop-filter:blur(9px)!important;-webkit-backdrop-filter:blur(9px)!important;box-shadow:none!important}.state{min-height:8px!important;font-size:8px!important;letter-spacing:.22em!important;color:rgba(210,255,143,.68)!important}.hint{margin-top:3px!important;font:400 10px/1.3 system-ui,sans-serif!important;color:rgba(255,255,255,.62)!important}
.controls{z-index:6!important;top:max(13px,env(safe-area-inset-top))!important;right:12px!important;gap:8px!important}.control{width:38px!important;height:38px!important;border-color:rgba(255,255,255,.10)!important;background:rgba(7,6,5,.22)!important;color:rgba(223,255,176,.70)!important;backdrop-filter:blur(8px)!important;-webkit-backdrop-filter:blur(8px)!important}.enter{background:rgba(7,6,5,.22)!important;backdrop-filter:blur(2px)!important}.enter button{border-color:rgba(183,243,74,.20)!important;background:rgba(8,7,6,.48)!important;color:#f3f7eb!important;box-shadow:0 16px 50px rgba(0,0,0,.28)!important}
@media(min-width:760px){.room{background-image:linear-gradient(180deg,rgba(5,5,4,.05),rgba(5,5,4,.01) 52%,rgba(5,5,4,.15)),url('/m4-assets/room-desktop.webp')!important;background-position:center center!important}.presence{width:min(24vw,300px)!important;height:min(24vw,300px)!important;transform:translateY(-2vh)!important}.presence.listening{transform:translateY(-2vh) scale(1.06)!important}.presence.thinking{transform:translateY(-1.5vh) scale(.94)!important}.presence.speaking{transform:translateY(-2vh) scale(1.02)!important}.status{bottom:25px!important}}
@media(max-width:420px){.presence{width:46vw!important;height:46vw!important}.status{max-width:70vw!important}}
</style>
'''

VISUAL_JS = r'''
<script id="m4-green-life">
(function(){
  let built=false,noise=null,hum=null,noiseGain=null,humGain=null,pulseTimer=null;
  function build(){
    if(built||!window.audioCtx||!window.master)return;
    built=true;const ctx=window.audioCtx;
    try{
      const buf=ctx.createBuffer(1,ctx.sampleRate*2,ctx.sampleRate),d=buf.getChannelData(0);let last=0;
      for(let i=0;i<d.length;i++){const w=Math.random()*2-1;last=last*.992+w*.008;d[i]=last*.22}
      noise=ctx.createBufferSource();noise.buffer=buf;noise.loop=true;
      const lp=ctx.createBiquadFilter();lp.type='lowpass';lp.frequency.value=180;
      noiseGain=ctx.createGain();noiseGain.gain.value=.022;noise.connect(lp).connect(noiseGain).connect(window.master);noise.start();
      hum=ctx.createOscillator();hum.type='sine';hum.frequency.value=37;
      humGain=ctx.createGain();humGain.gain.value=.03;hum.connect(humGain).connect(window.master);hum.start();
      const pulse=()=>{if(!humGain)return;const t=ctx.currentTime;humGain.gain.cancelScheduledValues(t);humGain.gain.setValueAtTime(.026,t);humGain.gain.linearRampToValueAtTime(.043,t+1.8);humGain.gain.linearRampToValueAtTime(.026,t+4.8)};
      pulse();pulseTimer=setInterval(pulse,5400);
    }catch(e){console.log('M4 room ambience unavailable',e)}
  }
  const oldAmbient=window.ambient;
  if(typeof oldAmbient==='function')window.ambient=function(){oldAmbient();try{if(window.master)window.master.gain.value=.14;build()}catch(e){}};
})();
</script>
'''


def enhance(html: str) -> str:
    if 'id="m4-presentation-green"' in html:
        return html
    html = html.replace("</head>", VISUAL_CSS + "</head>")
    html = html.replace("</body>", VISUAL_JS + "</body>")
    return html
