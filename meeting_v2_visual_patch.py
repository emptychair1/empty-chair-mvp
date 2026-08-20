"""Presentation-only enhancement for The Meeting v2.

Keeps the existing Meeting behavior, endpoints, voice, persistence, and audio playback.
Adds chamber depth, a stronger M4 presence, and local browser ambience.
"""

VISUAL_CSS = r'''
<style id="m4-presentation-v3">
html,body{background:#eef0ea!important}
.room{background:
 radial-gradient(ellipse at 50% 43%,rgba(255,255,255,1) 0 16%,rgba(248,249,245,.98) 31%,rgba(231,234,226,.96) 63%,rgba(211,216,206,.98) 100%)!important;
perspective:1100px}
.room:before{left:-18%!important;right:-18%!important;bottom:-42%!important;height:70%!important;background:radial-gradient(ellipse at 50% 0,rgba(112,125,105,.19),rgba(230,233,226,.04) 44%,rgba(245,245,240,0) 72%)!important;filter:blur(22px)!important}
.room:after{opacity:.34!important;background:
 linear-gradient(90deg,transparent 49.86%,rgba(55,66,51,.08) 50%,transparent 50.14%),
 radial-gradient(ellipse at 50% 47%,transparent 0 31%,rgba(70,82,66,.035) 31.2%,transparent 31.8% 43%,rgba(70,82,66,.025) 43.2%,transparent 43.8%)!important}
.chamber-depth{position:absolute;inset:-12%;z-index:0;pointer-events:none;overflow:hidden}
.chamber-depth:before,.chamber-depth:after{content:'';position:absolute;left:50%;transform:translateX(-50%);border-radius:50%;pointer-events:none}
.chamber-depth:before{top:-18%;width:min(150vw,1500px);height:74%;background:radial-gradient(ellipse at 50% 100%,rgba(255,255,255,.86),rgba(255,255,255,.18) 52%,transparent 73%);filter:blur(6px)}
.chamber-depth:after{bottom:-21%;width:min(130vw,1300px);height:56%;border:1px solid rgba(72,83,68,.09);box-shadow:0 -34px 100px rgba(73,84,70,.08),inset 0 20px 90px rgba(255,255,255,.52);background:radial-gradient(ellipse at 50% 2%,rgba(120,134,113,.11),transparent 63%)}
.light-column{position:absolute;z-index:0;left:50%;top:-4%;transform:translateX(-50%);width:min(48vw,520px);height:92%;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(255,255,255,.42) 27%,rgba(255,255,255,.84) 50%,rgba(255,255,255,.42) 73%,transparent);filter:blur(28px);opacity:.68;animation:m4column 11s ease-in-out infinite}
@keyframes m4column{0%,100%{opacity:.48;transform:translateX(-50%) scaleX(.92)}50%{opacity:.82;transform:translateX(-50%) scaleX(1.08)}}
.signal-field{position:absolute;z-index:1;left:50%;top:50%;transform:translate(-50%,-50%);width:min(92vw,760px);aspect-ratio:1;border-radius:50%;pointer-events:none;border:1px solid rgba(87,101,81,.06);box-shadow:0 0 0 54px rgba(88,102,83,.018),0 0 0 112px rgba(88,102,83,.012),0 0 120px rgba(112,131,105,.12);animation:m4field 9s ease-in-out infinite}
.signal-field:before,.signal-field:after{content:'';position:absolute;border-radius:50%;inset:12%;border:1px solid rgba(86,101,80,.07);animation:m4field2 13s ease-in-out infinite}
.signal-field:after{inset:28%;border-color:rgba(86,101,80,.085);animation-duration:7s;animation-direction:reverse}
@keyframes m4field{0%,100%{transform:translate(-50%,-50%) scale(.98);opacity:.58}50%{transform:translate(-50%,-50%) scale(1.025);opacity:.92}}
@keyframes m4field2{0%,100%{transform:scale(.96) rotate(0);opacity:.46}50%{transform:scale(1.05) rotate(5deg);opacity:.88}}
.presence{width:min(78vw,610px)!important;height:min(78vw,610px)!important;z-index:3!important;filter:drop-shadow(0 45px 65px rgba(45,58,42,.13)) drop-shadow(0 0 44px rgba(112,139,105,.11))!important}
.presence:before,.presence:after{content:'';position:absolute;border-radius:50%;pointer-events:none;inset:9%;border:1px solid rgba(94,111,88,.13);box-shadow:inset 0 0 42px rgba(255,255,255,.66),0 0 55px rgba(101,126,95,.08);animation:m4orbit 12s ease-in-out infinite}
.presence:after{inset:20%;border-color:rgba(94,111,88,.10);animation-duration:8s;animation-direction:reverse}
@keyframes m4orbit{0%,100%{transform:scale(.97) rotate(-2deg);opacity:.35}50%{transform:scale(1.04) rotate(3deg);opacity:.78}}
.presence svg{filter:contrast(1.045) saturate(.88)}
.membrane path:first-of-type{stroke:rgba(95,109,89,.5)!important;stroke-width:1.45!important}
.inner ellipse:first-of-type{opacity:.74!important}
.presence.listening:before{animation-duration:4.8s;box-shadow:inset 0 0 48px rgba(255,255,255,.78),0 0 72px rgba(108,139,102,.17)}
.presence.thinking:after{animation-duration:2.8s;opacity:.9}
.presence.speaking:before,.presence.speaking:after{border-color:rgba(98,126,91,.2);box-shadow:0 0 80px rgba(104,137,98,.18),inset 0 0 54px rgba(255,255,255,.72)}
.status{bottom:max(42px,calc(env(safe-area-inset-bottom) + 28px))!important;padding:14px 22px 13px;border:1px solid rgba(72,84,68,.08);border-radius:999px;background:rgba(251,252,248,.38);backdrop-filter:blur(14px);box-shadow:0 14px 42px rgba(57,68,53,.07);width:auto!important;min-width:min(84vw,390px);max-width:min(90vw,720px)}
.state{font-size:9px!important;letter-spacing:.22em!important;color:#626b5f!important}
.hint{font-size:13px!important;color:#737b70!important;margin-top:7px!important}
.enter{background:radial-gradient(ellipse at 50% 42%,rgba(255,255,255,.72),rgba(239,242,235,.88) 58%,rgba(220,225,215,.94))!important;backdrop-filter:blur(10px)!important}
.enter button{padding:16px 34px!important;font-size:21px!important;border-color:rgba(73,87,69,.16)!important;background:rgba(255,255,252,.72)!important;box-shadow:0 20px 70px rgba(63,75,59,.12),inset 0 1px 0 rgba(255,255,255,.8)!important}
.controls{top:max(18px,env(safe-area-inset-top))!important;right:20px!important}
.control{background:rgba(255,255,252,.52)!important;border-color:rgba(65,78,61,.11)!important;box-shadow:0 8px 24px rgba(55,66,52,.05)}
.ambient-label{position:absolute;z-index:5;left:22px;top:max(22px,env(safe-area-inset-top));font:500 9px ui-monospace,SFMono-Regular,monospace;letter-spacing:.2em;text-transform:uppercase;color:rgba(71,82,67,.42);pointer-events:none}
@media(max-width:650px){.presence{width:94vw!important;height:94vw!important}.signal-field{width:108vw}.status{min-width:86vw;padding:12px 18px}.ambient-label{left:14px;top:18px}}
</style>
'''

VISUAL_JS = r'''
<script id="m4-ambience-v3">
(function(){
  const room=document.getElementById('room');
  if(room){
    const depth=document.createElement('div'); depth.className='chamber-depth'; room.prepend(depth);
    const column=document.createElement('div'); column.className='light-column'; room.prepend(column);
    const field=document.createElement('div'); field.className='signal-field'; room.insertBefore(field, room.querySelector('.presence'));
    const label=document.createElement('div'); label.className='ambient-label'; label.textContent='M4 / SIGNAL CHAMBER'; room.appendChild(label);
  }

  let enhanced=false,noiseSource=null,noiseGain=null,lowOsc=null,lowGain=null,breathTimer=null;
  function buildAmbience(){
    if(enhanced || !window.audioCtx) return;
    enhanced=true;
    const ctx=window.audioCtx;
    try{
      const seconds=2, buffer=ctx.createBuffer(1,ctx.sampleRate*seconds,ctx.sampleRate),d=buffer.getChannelData(0);
      let last=0;
      for(let i=0;i<d.length;i++){const white=Math.random()*2-1;last=(last*.985)+(white*.015);d[i]=last*.34;}
      noiseSource=ctx.createBufferSource(); noiseSource.buffer=buffer; noiseSource.loop=true;
      const lp=ctx.createBiquadFilter(); lp.type='lowpass'; lp.frequency.value=240;
      noiseGain=ctx.createGain(); noiseGain.gain.value=.035;
      noiseSource.connect(lp).connect(noiseGain).connect(window.master); noiseSource.start();
      lowOsc=ctx.createOscillator(); lowOsc.type='sine'; lowOsc.frequency.value=31;
      lowGain=ctx.createGain(); lowGain.gain.value=.055;
      lowOsc.connect(lowGain).connect(window.master); lowOsc.start();
      const breathe=()=>{if(!window.audioCtx||!window.master)return; const t=ctx.currentTime; lowGain.gain.cancelScheduledValues(t);lowGain.gain.setValueAtTime(.038,t);lowGain.gain.linearRampToValueAtTime(.068,t+2.2);lowGain.gain.linearRampToValueAtTime(.038,t+4.8);};
      breathe(); breathTimer=setInterval(breathe,5200);
    }catch(e){console.log('M4 ambience enhancement unavailable',e)}
  }

  const originalAmbient=window.ambient;
  if(typeof originalAmbient==='function'){
    window.ambient=function(){
      originalAmbient();
      try{
        if(window.master) window.master.gain.value=.19;
        buildAmbience();
      }catch(e){console.log('M4 ambience start failed',e)}
    };
  }

  const originalVisual=window.visual;
  if(typeof originalVisual==='function'){
    window.visual=function(s,msg){
      originalVisual(s,msg);
      if(room){room.dataset.m4State=s||'present';}
    };
  }
})();
</script>
'''


def enhance(html: str) -> str:
    if 'id="m4-presentation-v3"' in html:
        return html
    html = html.replace("</head>", VISUAL_CSS + "</head>")
    html = html.replace("</body>", VISUAL_JS + "</body>")
    return html
