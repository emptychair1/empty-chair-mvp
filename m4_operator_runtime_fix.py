"""Runtime hardening, full Empty Chair branding, and owner-facing confidence UI."""
from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import m4_operator_observable


_original = m4_operator_observable.m4_operator_live


def _patched(request: Request):
    response = _original(request)
    if not isinstance(response, HTMLResponse):
        return response
    html = response.body.decode("utf-8")

    # Use the real app design system and logo instead of maintaining a second pseudo-brand.
    html = html.replace(
        '<title>M4 Live Operator</title>',
        '<title>Empty Chair · M4 Intelligence Center</title><link rel="stylesheet" href="/static/style.css?v=m4-brand-2">',
    )
    html = html.replace(
        '<div class="top"><div class="brand">EMPTY CHAIR<small>M4 // AUTONOMOUS RECOVERY</small></div>',
        '<div class="top"><div class="brand ec-brand"><img src="/static/empty-chair-logo-transparent.png?v=3" alt="Empty Chair"><div><b>M4 INTELLIGENCE CENTER</b><small>RANK · EXPLAIN · ACT · LEARN</small></div></div>',
    )
    html = html.replace('href="/demo">Demo home</a>', 'href="/">Dashboard</a>')
    html = html.replace(
        '<div class="ey">Observe → reason → offer → claim → book → learn</div><h1>Watch M4 close the loop.</h1>',
        '<div class="ey">EMPTY CHAIR // M4 INTELLIGENCE</div><h1>KNOW WHO TO CALL FIRST.</h1>',
    )
    html = html.replace(
        'M4 narrates what she is doing, chooses the highest-value gap, ranks demand, sends a synthetic offer, receives a synthetic claim, places the booking on the calendar, and updates recovered revenue. No real customer is contacted.',
        'M4 ranks the demand around every empty chair, explains the evidence behind the choice, knows when the evidence is weak, and learns what information would make the next decision better. This demo uses synthetic offers only.',
    )

    # Replace the voice function. ElevenLabs remains first choice, but the owner always
    # hears M4: browser speech is an explicit fallback if server TTS is unavailable.
    old = "async function speak(key){try{const f=new FormData();f.append('key',key);const r=await fetch('/api/m4/operator/narrate',{method:'POST',body:f,cache:'no-store'}),j=await r.json();if(j.text)log.textContent+='\\nM4: '+j.text;if(j.audio_base64){voiceStatus.textContent='M4 is speaking';await new Promise(resolve=>{const a=new Audio('data:audio/mpeg;base64,'+j.audio_base64);a.onended=resolve;a.onerror=resolve;a.play().catch(resolve)})}else{voiceStatus.textContent='M4 voice unavailable; narration shown as text.'}}catch(e){voiceStatus.textContent='M4 voice unavailable; narration shown as text.'}}"
    new = "let voiceQueue=Promise.resolve();function browserSpeak(text){return new Promise(resolve=>{if(!text||!('speechSynthesis' in window)){resolve();return}speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.rate=.92;u.pitch=.82;u.volume=1;const voices=speechSynthesis.getVoices();u.voice=voices.find(v=>/samantha|ava|allison|victoria|female/i.test(v.name))||voices.find(v=>/^en/i.test(v.lang))||null;u.onend=resolve;u.onerror=resolve;voiceStatus.textContent='M4 is speaking · device voice fallback';speechSynthesis.speak(u);setTimeout(resolve,15000)})}async function speakNow(key){let text='';try{const f=new FormData();f.append('key',key);const ctl=new AbortController();const timer=setTimeout(()=>ctl.abort(),12000);const r=await fetch('/api/m4/operator/narrate',{method:'POST',body:f,cache:'no-store',signal:ctl.signal});clearTimeout(timer);const j=await r.json();text=j.text||'';if(text)log.textContent+='\\nM4: '+text;if(j.audio_base64){voiceStatus.textContent='M4 is speaking · ElevenLabs';const a=new Audio('data:audio/mpeg;base64,'+j.audio_base64);a.volume=1;await new Promise(resolve=>{let finished=false;const done=()=>{if(finished)return;finished=true;resolve()};a.onended=done;a.onerror=async()=>{await browserSpeak(text);done()};a.play().catch(async()=>{await browserSpeak(text);done()});setTimeout(done,18000)});return}if(text){await browserSpeak(text);return}voiceStatus.textContent='M4 narration unavailable.'}catch(e){if(text)await browserSpeak(text);else voiceStatus.textContent='M4 voice request failed: '+(e&&e.message?e.message:String(e))}}function speak(key){voiceQueue=voiceQueue.then(()=>speakNow(key)).catch(()=>{});return new Promise(resolve=>setTimeout(resolve,220))}"
    html = html.replace(old, new)

    old_run = "run.onclick=async()=>{run.disabled=true;offer.classList.remove('show');"
    new_run = "run.onclick=async()=>{run.disabled=true;run.textContent='M4 RUNNING…';state('Recovery run started','acting');offer.classList.remove('show');"
    html = html.replace(old_run, new_run)

    old_catch = "catch(e){state('Interrupted: '+e.message,'');run.disabled=false}};load().catch(e=>{log.textContent=e.message;run.disabled=true})"
    new_catch = "catch(e){state('Interrupted: '+(e&&e.message?e.message:String(e)),'');voiceStatus.textContent='Recovery stopped — see M4 log.';run.disabled=false;run.textContent='Run full recovery'}};load().then(()=>{run.textContent='Run full recovery'}).catch(e=>{log.textContent='M4 load error: '+(e&&e.message?e.message:String(e));m4state.textContent='operator unavailable';run.disabled=false;run.textContent='Retry full recovery'})"
    html = html.replace(old_catch, new_catch)

    old_sent = "offer.classList.add('show');state('Offer sent. Waiting for customer behavior.','acting');await speak('sent')}"
    new_sent = "offer.classList.add('show');state('Offer sent. Waiting for customer behavior.','acting');run.textContent='Run full recovery';await speak('sent')}"
    html = html.replace(old_sent, new_sent)

    brand_css = r'''
    :root{--bg:var(--ink);--panel:#0d0f0d;--line:var(--line-soft);--inkText:var(--cream);--muted:var(--muted);--g:var(--signal);--good:var(--green)}
    body{background:#080908!important;color:var(--cream)!important;font-family:var(--body)!important}body:before{opacity:.13!important}.shell{max-width:1500px!important;padding:0 28px 60px!important}.top{min-height:92px;padding:14px 0!important;border-bottom:1px solid var(--line)!important;background:#080908!important;position:sticky;top:0;z-index:25}.ec-brand{display:flex!important;align-items:center;gap:16px;letter-spacing:0!important}.ec-brand img{width:150px;max-height:62px;object-fit:contain;display:block}.ec-brand b{display:block;font-family:var(--cartoon);font-size:23px;font-weight:400;letter-spacing:.02em;color:var(--cream)}.ec-brand small{color:var(--signal)!important;font:800 9px var(--body)!important;letter-spacing:.11em!important}.btn{min-height:44px!important;padding:0 18px!important;border-radius:0!important;border:1px solid var(--signal)!important;background:var(--signal)!important;color:#080908!important;font-family:var(--cartoon)!important;font-size:16px!important;font-weight:400!important;letter-spacing:.02em!important;box-shadow:3px 3px 0 #000}.btn.alt{background:#0b0d0b!important;color:var(--cream)!important;border-color:var(--line)!important}.hero{padding:38px 0 28px!important}.hero h1{font-family:var(--cartoon)!important;font-size:clamp(52px,7vw,94px)!important;font-weight:400!important;letter-spacing:.01em!important;line-height:.86!important;text-transform:uppercase}.hero p{color:var(--cream-dim)!important;font-size:14px}.ey{color:var(--signal)!important;font-family:var(--cartoon)!important;font-size:13px!important;font-weight:400!important;letter-spacing:.04em!important}.m4,.metric,.pane,.opening,.person,.node,.calendar-card,.log,.offer-pop{border-radius:2px!important;background:#0d0f0d!important;border-color:var(--line)!important;box-shadow:4px 4px 0 #000}.m4{background:radial-gradient(circle,rgba(199,255,62,.11),#0d0f0d 58%)!important}.cell{background:rgba(199,255,62,.18)!important;box-shadow:0 0 28px rgba(199,255,62,.5),0 0 90px rgba(199,255,62,.13)!important}.metrics{gap:8px!important}.metric{padding:17px!important}.metric b{font-family:var(--display)!important;font-size:29px!important}.metric small{font-family:var(--cartoon)!important;font-size:12px!important;color:var(--cream-dim)!important}.grid{gap:8px!important;background:transparent!important;border:0!important}.pane{min-height:590px!important;padding:20px!important}.pane h2{font-family:var(--cartoon)!important;font-size:29px!important;font-weight:400!important;text-transform:uppercase}.lane{border:1px solid var(--line)!important;background:#090b09}.lane h3{font-family:var(--cartoon)!important;font-size:13px!important;color:var(--cream-dim)!important}.opening.active,.person.focus,.calendar-card.flash,.node.active{border-color:var(--signal)!important;box-shadow:inset 3px 0 0 var(--signal)!important}.score,.revenue b,.offer-state{color:var(--signal)!important}.voice{margin-top:12px!important;padding:10px 12px;border-left:2px solid var(--signal);background:#090b09;color:var(--cream-dim)!important;font-size:10px!important}.log{color:var(--cream-dim)!important}.claim{border-radius:0!important;background:var(--signal)!important;color:#080908!important;font-family:var(--cartoon)!important;font-size:16px!important}.person{position:relative}.m4-confidence{display:inline-flex;align-items:center;gap:6px;margin-top:9px;padding:5px 8px;border:1px solid #455045;font:900 9px ui-monospace,monospace;letter-spacing:.08em}.m4-confidence.high{border-color:var(--signal);color:var(--signal);background:rgba(199,255,62,.06)}.m4-confidence.medium{border-color:#d8b65a;color:#e4c871}.m4-confidence.low{border-color:#b96565;color:#e39191}.m4-action{margin-left:6px;color:var(--cream-dim)}.m4-explain{margin-top:10px;padding-top:9px;border-top:1px solid var(--line-soft)}.m4-explain b{font:400 13px var(--cartoon);letter-spacing:.03em;text-transform:uppercase;color:var(--cream-dim)}.m4-explain ul{list-style:none;padding:0;margin:6px 0 0}.m4-explain li{font-size:10px;line-height:1.45;color:var(--cream-dim);margin:3px 0}.m4-explain li.good:before{content:'+ ';color:var(--signal);font-weight:900}.m4-explain li.risk:before{content:'− ';color:#e39191;font-weight:900}.m4-learning{margin-top:8px;padding:7px 8px;border-left:2px solid #d8b65a;background:#11130e;color:#c9bea0;font-size:9px;line-height:1.45}.person.focus .m4-explain{display:block}@media(max-width:760px){.shell{padding:0 15px 50px!important}.top{align-items:flex-start!important;flex-direction:column}.ec-brand img{width:125px}.hero{padding-top:26px!important}.hero h1{font-size:55px!important}}
    '''
    html = html.replace("</style>", brand_css + "</style>")

    old_card = "function card(c){const d=document.createElement('div');d.className='person';d.dataset.id=c.customer_id;d.innerHTML=`<b>${c.name||c.customer_id}</b><span>booking ${Math.round(c.booking_probability*100)}% · uplift ${Math.round(c.incremental_uplift*100)}%</span><span class=\"score\">queue ${c.queue_score} · EV $${Number(c.expected_value||0).toFixed(0)}</span>`;return d}"
    new_card = "function card(c){const d=document.createElement('div');d.className='person';d.dataset.id=c.customer_id;const label=(c.m4_confidence_label||'LOW').toLowerCase(),score=Number(c.m4_confidence_score||0),action=c.recommended_action==='ACT'?'ACT':c.recommended_action==='RECOMMEND'?'RECOMMEND':'LEARN FIRST';const why=(c.why_this_person||[]).slice(0,4).map(x=>`<li class=\"good\">${x}</li>`).join('');const risks=(c.risk_factors||[]).slice(0,2).map(x=>`<li class=\"risk\">${x}</li>`).join('');const missing=(c.missing_high_value_signals||[]).slice(0,3);const learn=missing.length?`<div class=\"m4-learning\"><b>M4 WANTS TO LEARN:</b> ${missing.join(' · ')}</div>`:'';d.innerHTML=`<b>${c.name||c.customer_id}</b><span>booking ${Math.round(c.booking_probability*100)}% · uplift ${Math.round(c.incremental_uplift*100)}%</span><span class=\"score\">queue ${c.queue_score} · EV $${Number(c.expected_value||0).toFixed(0)}</span><div class=\"m4-confidence ${label}\">${(c.m4_confidence_label||'LOW')} ${score}% <span class=\"m4-action\">→ ${action}</span></div><div class=\"m4-explain\"><b>Why M4 ranks this person</b><ul>${why||'<li>Limited supporting evidence</li>'}${risks}</ul>${learn}</div>`;return d}"
    html = html.replace(old_card, new_card)

    old_top = "top=ranked[0];document.getElementById('mev').textContent='$'+Number(top.expected_value||0).toFixed(0);document.getElementById('mscore').textContent=top.queue_score;"
    new_top = "top=ranked[0];document.getElementById('mev').textContent='$'+Number(top.expected_value||0).toFixed(0);document.getElementById('mscore').textContent=top.queue_score;log.textContent+='\\n\\nOWNER VIEW // '+(top.m4_confidence_label||'LOW')+' CONFIDENCE '+Number(top.m4_confidence_score||0)+'% → '+(top.recommended_action||'LEARN_OR_FALLBACK');if((top.why_this_person||[]).length)log.textContent+='\\nWHY: '+top.why_this_person.slice(0,3).join(' • ');if((top.risk_factors||[]).length)log.textContent+='\\nRISK: '+top.risk_factors.slice(0,2).join(' • ');"
    html = html.replace(old_top, new_top)

    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


for route in core.app.routes:
    if getattr(route, "path", None) == "/m4-operator-live" and getattr(route, "methods", None) and "GET" in route.methods:
        route.endpoint = _patched
        break
