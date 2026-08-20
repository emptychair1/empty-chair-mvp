"""Presentation-only visual layer for The Meeting.

Uses clean generated tattoo-shop room photography for mobile/desktop and one
image-based M4 cellular presence that changes continuously with Meeting state.
Voice, recording, reasoning, persistence, and endpoints remain untouched.
"""
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "m4_assets"


def _asset(name: str) -> str:
    try:
        raw = (_ASSETS / name).read_text(encoding="utf-8").strip()
        return "data:image/webp;base64," + raw
    except Exception:
        return ""


BG_MOBILE = _asset("bg_mobile.b64")
BG_DESKTOP = _asset("bg_desktop.b64")
M4_CELL = _asset("present.b64")

VISUAL_CSS = r'''
<style id="m4-presentation-v5">
html,body{background:#090807!important}
.room{background-color:#090807!important;background-image:linear-gradient(rgba(7,6,5,.12),rgba(7,6,5,.26)),url("__BG_MOBILE__")!important;background-size:cover!important;background-repeat:no-repeat!important;background-position:center center!important}
@media(min-width:760px){.room{background-image:linear-gradient(rgba(7,6,5,.10),rgba(7,6,5,.22)),url("__BG_DESKTOP__")!important;background-position:center center!important}}
.room:before{content:''!important;position:absolute!important;inset:0!important;background:radial-gradient(circle at 50% 45%,transparent 0 21%,rgba(0,0,0,.035) 47%,rgba(0,0,0,.30) 100%)!important;filter:none!important;border-radius:0!important;pointer-events:none!important}
.room:after{content:''!important;position:absolute!important;inset:0!important;background:linear-gradient(180deg,rgba(0,0,0,.10),transparent 26%,transparent 72%,rgba(0,0,0,.29))!important;opacity:1!important;pointer-events:none!important}
.grain{opacity:.025!important}
.chamber-depth,.light-column,.signal-field,.ambient-label{display:none!important}
.presence{position:relative!important;z-index:3!important;width:min(66vw,430px)!important;height:min(66vw,430px)!important;display:block!important;filter:drop-shadow(0 28px 44px rgba(0,0,0,.46)) drop-shadow(0 0 30px rgba(255,194,118,.12))!important;transform-origin:50% 50%!important;transition:transform .9s cubic-bezier(.2,.7,.2,1),filter .8s ease!important}
.presence svg{display:none!important}
.presence:before{content:''!important;display:block!important;position:absolute!important;inset:0!important;border:0!important;border-radius:44% 56% 48% 52%/52% 47% 53% 48%!important;background-image:url("__M4_CELL__")!important;background-size:contain!important;background-position:center!important;background-repeat:no-repeat!important;box-shadow:none!important;opacity:.92!important;animation:m4Idle 7.8s ease-in-out infinite!important;filter:brightness(.88) saturate(.72) contrast(1.03)!important;will-change:transform,filter,opacity!important}
.presence:after{content:''!important;display:block!important;position:absolute!important;inset:16%!important;border:0!important;border-radius:50%!important;background:radial-gradient(circle,rgba(255,220,170,.16),rgba(255,196,112,.055) 43%,transparent 72%)!important;filter:blur(22px)!important;opacity:.48!important;animation:m4Halo 5.2s ease-in-out infinite!important;pointer-events:none!important}
.presence.listening:before{animation:m4Listen 3.5s ease-in-out infinite!important;filter:brightness(1.02) saturate(.82) contrast(1.04)!important}
.presence.listening:after{opacity:.68!important;animation-duration:3.1s!important}
.presence.thinking:before{animation:m4Think 2.8s ease-in-out infinite!important;filter:brightness(.80) saturate(.65) contrast(1.08)!important}
.presence.thinking:after{opacity:.38!important;animation-duration:2.2s!important}
.presence.speaking:before{animation:m4Speak 1.4s ease-in-out infinite!important;filter:brightness(1.12) saturate(.90) contrast(1.04)!important}
.presence.speaking:after{opacity:.78!important;animation-duration:1.25s!important}
@keyframes m4Idle{0%,100%{transform:scale(.965) rotate(-.45deg) skewX(-.3deg)}34%{transform:scale(1.006) rotate(.32deg) skewX(.25deg)}67%{transform:scale(.982) rotate(-.1deg) skewY(.25deg)}}
@keyframes m4Listen{0%,100%{transform:scale(1.00) rotate(-.2deg)}50%{transform:scale(1.055) rotate(.35deg)}}
@keyframes m4Think{0%,100%{transform:scale(.925) rotate(-.8deg) skewX(-.45deg)}50%{transform:scale(.972) rotate(.65deg) skewY(.35deg)}}
@keyframes m4Speak{0%,100%{transform:scale(.992) rotate(-.15deg)}45%{transform:scale(1.055) rotate(.25deg)}70%{transform:scale(1.018) rotate(-.18deg)}}
@keyframes m4Halo{0%,100%{transform:scale(.90);opacity:.34}50%{transform:scale(1.11);opacity:.66}}
.m4-vesicle{position:absolute;z-index:4;width:5px;height:5px;border-radius:50%;background:rgba(255,231,196,.68);box-shadow:0 0 12px rgba(255,193,112,.54);pointer-events:none;opacity:.25}
.m4-v1{left:23%;top:33%;animation:m4V1 10s ease-in-out infinite}.m4-v2{right:22%;top:26%;width:3px;height:3px;animation:m4V2 8.5s ease-in-out infinite}.m4-v3{right:19%;bottom:31%;width:4px;height:4px;animation:m4V3 11s ease-in-out infinite}.m4-v4{left:28%;bottom:25%;width:3px;height:3px;animation:m4V4 9.3s ease-in-out infinite}
@keyframes m4V1{0%,100%{transform:translate(0,0);opacity:.15}48%{transform:translate(16px,-19px);opacity:.52}}@keyframes m4V2{0%,100%{transform:translate(0,0);opacity:.16}55%{transform:translate(-13px,18px);opacity:.58}}@keyframes m4V3{0%,100%{transform:translate(0,0);opacity:.14}50%{transform:translate(-18px,-10px);opacity:.50}}@keyframes m4V4{0%,100%{transform:translate(0,0);opacity:.15}46%{transform:translate(14px,11px);opacity:.48}}
.status{bottom:max(18px,calc(env(safe-area-inset-bottom) + 12px))!important;width:auto!important;min-width:0!important;max-width:86vw!important;padding:7px 11px!important;border:1px solid rgba(255,255,255,.07)!important;border-radius:999px!important;background:rgba(7,6,5,.34)!important;backdrop-filter:blur(11px)!important;box-shadow:0 8px 28px rgba(0,0,0,.12)!important}
.state{min-height:9px!important;font-size:8px!important;letter-spacing:.22em!important;color:rgba(255,244,228,.58)!important}
.hint{margin-top:2px!important;font:400 10px/1.3 Georgia,serif!important;color:rgba(255,244,228,.68)!important}
.controls{top:max(14px,env(safe-area-inset-top))!important;right:12px!important}.control{width:35px!important;height:35px!important;border-color:rgba(255,255,255,.10)!important;background:rgba(7,6,5,.28)!important;color:rgba(255,244,228,.70)!important;backdrop-filter:blur(10px)!important}
.enter{background:rgba(7,6,5,.26)!important;backdrop-filter:blur(4px)!important}.enter button{border-color:rgba(255,255,255,.17)!important;background:rgba(8,7,6,.54)!important;color:#f6eee3!important;box-shadow:0 16px 55px rgba(0,0,0,.32)!important;font-size:20px!important;padding:15px 30px!important}
.transcript{display:none!important}
@media(max-width:650px){.presence{width:72vw!important;height:72vw!important;transform:translateY(-2vh)}.status{bottom:max(16px,calc(env(safe-area-inset-bottom) + 10px))!important}.hint{font-size:9px!important}}
</style>
'''.replace("__BG_MOBILE__", BG_MOBILE).replace("__BG_DESKTOP__", BG_DESKTOP).replace("__M4_CELL__", M4_CELL)

VISUAL_JS = r'''
<script id="m4-life-v5">
(function(){
 const p=document.getElementById('presence');
 if(p&&!p.querySelector('.m4-vesicle')){
   ['m4-v1','m4-v2','m4-v3','m4-v4'].forEach(c=>{const i=document.createElement('i');i.className='m4-vesicle '+c;p.appendChild(i)});
 }
 let ctx=null,gain=null,started=false,muted=false;
 function brown(c,seconds){const b=c.createBuffer(1,c.sampleRate*seconds,c.sampleRate),d=b.getChannelData(0);let last=0;for(let i=0;i<d.length;i++){last=last*.992+(Math.random()*2-1)*.008;d[i]=last*.6}return b}
 function pulse(){if(!ctx||!gain||muted)return;const t=ctx.currentTime,o=ctx.createOscillator(),g=ctx.createGain();o.type='sine';o.frequency.setValueAtTime(62,t);o.frequency.exponentialRampToValueAtTime(38,t+.56);g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(.075,t+.035);g.gain.exponentialRampToValueAtTime(.0001,t+.92);o.connect(g).connect(gain);o.start(t);o.stop(t+.96)}
 async function start(){if(started)return;started=true;try{ctx=new(window.AudioContext||window.webkitAudioContext)();await ctx.resume();gain=ctx.createGain();gain.gain.value=.16;gain.connect(ctx.destination);const n=ctx.createBufferSource(),lp=ctx.createBiquadFilter(),ng=ctx.createGain();n.buffer=brown(ctx,3);n.loop=true;lp.type='lowpass';lp.frequency.value=180;ng.gain.value=.052;n.connect(lp).connect(ng).connect(gain);n.start();const h=ctx.createOscillator(),hg=ctx.createGain();h.type='sine';h.frequency.value=34;hg.gain.value=.044;h.connect(hg).connect(gain);h.start();const a=ctx.createOscillator(),ag=ctx.createGain();a.type='sine';a.frequency.value=69;ag.gain.value=.009;a.connect(ag).connect(gain);a.start();pulse();setInterval(pulse,5200)}catch(e){console.log('M4 ambience unavailable',e)}}
 const enter=document.getElementById('enterButton');if(enter)enter.addEventListener('click',start,{once:true});
 const mute=document.getElementById('mute');if(mute)mute.addEventListener('click',()=>{muted=!muted;if(ctx&&gain)gain.gain.setTargetAtTime(muted?0:.16,ctx.currentTime,.18)});
})();
</script>
'''


def enhance(html: str) -> str:
    if 'id="m4-presentation-v5"' in html:
        return html
    html = html.replace("</head>", VISUAL_CSS + "</head>")
    html = html.replace("</body>", VISUAL_JS + "</body>")
    return html
