"""Low-noise presentation layer for Digital Consultations.

This module changes presentation only. It performs no database or network work at
import time and leaves messaging, quotes, revisions, deposits, and booking routes
untouched.
"""
from fastapi import Request
from fastapi.responses import Response

import app as core


_CLEAN_UI = r"""
<style id="ec-consult-clean-ui">
/* Conversation first. Secondary workflow controls stay available, but quiet. */
.consult-shell .consult-wrap{width:min(900px,calc(100% - 28px));padding-top:16px}
.consult-shell .consult-brandbar{margin-bottom:10px;padding:8px 0 14px;min-height:64px}
.consult-shell .consult-person-identity{grid-template-columns:48px minmax(0,1fr);gap:11px}
.consult-shell .consult-user-avatar-large{width:48px!important;height:48px!important;min-width:48px!important}
.consult-shell .consult-brandbar h1,.consult-shell .consult-title{font-size:31px!important;line-height:1!important;margin:2px 0!important;text-transform:none!important}
.consult-shell .consult-kicker{font-size:9px;opacity:.72;letter-spacing:.11em}
.consult-shell .consult-brandbar small{font-size:11px;color:#858d82}

/* Make the timeline feel like messaging, not a dashboard. */
.consult-shell .consult-chat{min-height:58vh;gap:7px;padding:12px 2px 82px}
.consult-shell .consult-msg{max-width:min(72%,600px);padding:10px 12px;border:0!important;box-shadow:none!important;line-height:1.42;font-size:14px}
.consult-shell .consult-msg.inbound{background:#151915;border-radius:5px 16px 16px 16px}
.consult-shell .consult-msg.outbound{background:#c7ff3e;border-radius:16px 5px 16px 16px}
.consult-shell .consult-msg small{font-size:8px;margin-top:4px;opacity:.38}

/* Composer should be the dominant control. */
.consult-shell .consult-compose{grid-template-columns:minmax(0,1fr) 78px;gap:7px;padding:7px;bottom:8px;border:1px solid #2d332b;border-radius:14px;background:rgba(10,12,10,.96);box-shadow:0 12px 30px rgba(0,0,0,.32)}
.consult-shell .consult-compose textarea{min-height:46px;max-height:130px;padding:11px 12px;border:0;border-radius:10px;background:#151915;resize:none}
.consult-shell .consult-compose textarea:focus{box-shadow:inset 0 0 0 1px #6f873d}
.consult-shell .consult-send{min-width:0;min-height:46px;padding:0 13px;border-radius:10px;box-shadow:none!important;font-family:Inter,system-ui,sans-serif;font-size:13px;font-weight:900;letter-spacing:0}
.consult-shell .consult-send:hover{transform:none;box-shadow:none!important}

/* One quiet workflow menu replaces a row of competing actions. */
.ec-consult-actions{position:relative;margin-left:auto;flex:0 0 auto}
.ec-consult-actions-toggle{height:38px;padding:0 13px;border:1px solid #353c32;border-radius:9px;background:#101310;color:#d9ddd5;font:800 12px Inter,system-ui,sans-serif;cursor:pointer}
.ec-consult-actions-toggle:hover{border-color:#607045;color:#fff}
.ec-consult-actions-menu{display:none;position:absolute;right:0;top:44px;z-index:50;width:220px;padding:6px;border:1px solid #3a4135;border-radius:12px;background:#0d100d;box-shadow:0 16px 40px rgba(0,0,0,.55)}
.ec-consult-actions.open .ec-consult-actions-menu{display:grid;gap:4px}
.ec-consult-actions-menu>a,.ec-consult-actions-menu>form,.ec-consult-actions-menu>button{display:block;width:100%;margin:0!important}
.ec-consult-actions-menu a,.ec-consult-actions-menu button{width:100%;min-height:40px!important;padding:9px 10px!important;border:0!important;border-radius:8px!important;background:transparent!important;color:#e5e8e1!important;box-shadow:none!important;text-align:left!important;font:800 12px Inter,system-ui,sans-serif!important;text-decoration:none!important;cursor:pointer}
.ec-consult-actions-menu a:hover,.ec-consult-actions-menu button:hover{background:#171c15!important;color:#c7ff3e!important;transform:none!important}
.ec-consult-actions-menu form button{display:block}

/* Workflow cards remain visible but stop competing with messages. */
.ec-quiet-workflow{margin:7px 0!important;padding:10px 12px!important;border:1px solid #292f27!important;border-radius:10px!important;background:#0c0f0c!important;box-shadow:none!important;color:#aeb5aa!important;font-size:12px!important}
.ec-quiet-workflow h1,.ec-quiet-workflow h2,.ec-quiet-workflow h3,.ec-quiet-workflow strong{font-family:Inter,system-ui,sans-serif!important;font-size:12px!important;letter-spacing:0!important;text-transform:none!important}
.ec-quiet-workflow img{max-height:120px!important;width:auto!important;border-radius:7px!important}

/* Inbox: clearer hierarchy, less card chrome. */
.consult-shell .consult-list{gap:2px}
.consult-shell .consult-thread{grid-template-columns:42px minmax(0,1fr)!important;gap:11px!important;padding:12px 8px!important;border:0!important;border-bottom:1px solid #20251f!important;background:transparent!important;box-shadow:none!important;transform:none!important}
.consult-shell .consult-thread:hover{background:#0d100d!important;border-color:#2b3228!important}
.consult-shell .consult-user-avatar{width:42px!important;height:42px!important;min-width:42px!important;box-shadow:none!important}
.consult-shell .consult-thread-name{font-size:14px;margin-bottom:2px}
.consult-shell .consult-thread-preview{font-size:12px!important;color:#9fa69b!important}
.consult-shell .consult-thread-meta{font-size:9px;margin-top:3px}

@media(max-width:620px){
 .consult-shell .consult-wrap{width:calc(100% - 16px);padding-top:8px}
 .consult-shell .consult-brandbar{gap:8px;margin-bottom:4px}
 .consult-shell .consult-person-identity{grid-template-columns:40px minmax(0,1fr);gap:9px}
 .consult-shell .consult-user-avatar-large{width:40px!important;height:40px!important;min-width:40px!important}
 .consult-shell .consult-brandbar h1,.consult-shell .consult-title{font-size:27px!important}
 .consult-shell .consult-msg{max-width:84%;font-size:14px}
 .consult-shell .consult-compose{grid-template-columns:minmax(0,1fr) 64px;padding:6px}
 .consult-shell .consult-send{min-height:44px;padding:0 9px}
 .ec-consult-actions-toggle{height:36px;padding:0 10px}
 .ec-consult-actions-menu{position:fixed;left:10px;right:10px;top:auto;bottom:76px;width:auto}
}
</style>
<script id="ec-consult-clean-ui-js">
(()=>{
 const exactThread=/^\/consultations\/[^/]+\/?$/;
 if(!exactThread.test(location.pathname)) return;
 const boot=()=>{
   const header=document.querySelector('.consult-brandbar, header');
   const compose=document.querySelector('.consult-compose');
   if(!header||!compose) return;

   const send=compose.querySelector('button[type="submit"]');
   if(send) send.textContent='Send';
   const area=compose.querySelector('textarea');
   if(area){
     const current=area.getAttribute('placeholder')||'';
     area.setAttribute('placeholder',current.replace(/^Reply to /,'Message ').replace(/…$/,'…'));
     area.setAttribute('rows','1');
   }

   // Consolidate workflow actions without changing their hrefs/forms or behavior.
   const labels=['Create Quote','Send Revision','Schedule Appointment','Simulate Deposit Paid'];
   const matches=[];
   document.querySelectorAll('a,button').forEach(el=>{
     const t=(el.textContent||'').trim();
     if(labels.some(label=>t.includes(label))) matches.push(el);
   });
   if(matches.length && !document.querySelector('.ec-consult-actions')){
     const wrap=document.createElement('div'); wrap.className='ec-consult-actions';
     const toggle=document.createElement('button'); toggle.type='button'; toggle.className='ec-consult-actions-toggle'; toggle.textContent='Actions ···'; toggle.setAttribute('aria-expanded','false');
     const menu=document.createElement('div'); menu.className='ec-consult-actions-menu';
     wrap.append(toggle,menu); header.appendChild(wrap);
     const moved=new Set();
     matches.forEach(el=>{
       const form=el.closest('form');
       const node=form&&form!==compose?form:el;
       if(moved.has(node)||wrap.contains(node)) return;
       moved.add(node); menu.appendChild(node);
     });
     toggle.addEventListener('click',e=>{e.stopPropagation();const open=wrap.classList.toggle('open');toggle.setAttribute('aria-expanded',open?'true':'false')});
     document.addEventListener('click',e=>{if(!wrap.contains(e.target)){wrap.classList.remove('open');toggle.setAttribute('aria-expanded','false')}});
   }

   // De-emphasize workflow summaries while preserving all information/actions.
   document.querySelectorAll('main > div, main > section, .consult-wrap > div, .consult-wrap > section').forEach(el=>{
     if(el===header||el===compose||el.classList.contains('consult-chat')||el.closest('.consult-chat')||el.classList.contains('ec-consult-actions')) return;
     const text=(el.textContent||'').toLowerCase();
     if(text.includes('quote v')||text.includes('revision r')||text.includes('deposit paid')||text.includes('ready to schedule')||text.includes('booked')) el.classList.add('ec-quiet-workflow');
   });

   // Keep the newest messages in view without forcing a reload or changing data.
   requestAnimationFrame(()=>window.scrollTo({top:document.body.scrollHeight,behavior:'instant'}));
 };
 if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
</script>
"""


@core.app.middleware("http")
async def simplify_consultation_interface(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path.rstrip("/")
    if not path.startswith("/consultations") or path == "/consultations" or "text/html" not in response.headers.get("content-type", "").lower():
        return response
    # Only the actual message thread gets this treatment. Quote/revision creation pages
    # keep their purpose-built forms.
    parts = [p for p in path.split("/") if p]
    if len(parts) != 2 or parts[0] != "consultations":
        return response
    chunks=[]
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    body=b"".join(chunks).decode("utf-8",errors="replace")
    if "ec-consult-clean-ui" not in body:
        body=body.replace("</body>",_CLEAN_UI+"</body>",1)
    headers=dict(response.headers)
    headers.pop("content-length",None)
    return Response(content=body,status_code=response.status_code,headers=headers,media_type="text/html",background=response.background)
