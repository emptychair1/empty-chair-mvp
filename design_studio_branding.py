"""Design Studio brand layer for the consultation experience.

Presentation-only. No database or network work occurs at import time. Existing
consultation, quote, revision, deposit, and booking behavior remains unchanged.
"""
from fastapi import Request
from fastapi.responses import Response

import app as core


_DESIGN_STUDIO_UI = r"""
<style id="ec-design-studio-brand">
.ec-design-hero{position:relative;overflow:hidden;margin:4px 0 20px;border:1px solid #30362c;border-radius:14px;background:#090b09;min-height:220px;box-shadow:0 12px 34px rgba(0,0,0,.28)}
.ec-design-hero img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;object-position:center}
.ec-design-hero:after{content:'';position:absolute;inset:0;background:linear-gradient(90deg,rgba(5,6,5,.72),transparent 46%),linear-gradient(0deg,rgba(5,6,5,.35),transparent 45%);pointer-events:none}
.ec-design-hero-copy{position:absolute;z-index:2;left:22px;bottom:20px;max-width:420px}.ec-design-hero-copy .ey{margin-bottom:5px}.ec-design-hero-copy h2{margin:0;font-family:'Bangers',Impact,sans-serif;font-size:40px;font-weight:400;line-height:.95;letter-spacing:.015em}.ec-design-hero-copy p{margin:7px 0 0;color:#d4d8cf;font-size:13px;line-height:1.45}
.ec-design-studio-thread .consult-msg.outbound{position:relative;margin-right:44px}
.ec-design-studio-thread .ec-artist-bubble-avatar{position:absolute;right:-46px;bottom:-2px;width:36px;height:36px;border-radius:50%;object-fit:cover;object-position:center;border:2px solid #c7ff3e;background:#eee7d7;box-shadow:0 2px 10px rgba(0,0,0,.4)}
.ec-design-studio-thread .consult-msg.outbound .ec-artist-bubble-avatar+div{min-width:0}
@media(max-width:620px){.ec-design-hero{min-height:170px;margin-bottom:13px}.ec-design-hero-copy{left:14px;right:14px;bottom:13px}.ec-design-hero-copy h2{font-size:31px}.ec-design-hero-copy p{display:none}.ec-design-studio-thread .consult-msg.outbound{margin-right:39px}.ec-design-studio-thread .ec-artist-bubble-avatar{right:-40px;width:32px;height:32px}}
</style>
<script id="ec-design-studio-js">
(()=>{
 const HERO='/static/design-studio-hero.png?v=1';
 const HEAD='/static/design-studio-artist-head.png?v=1';
 const boot=()=>{
   document.body.classList.add('ec-design-studio');
   const path=location.pathname.replace(/\/$/,'');
   document.title=document.title.replace(/Digital Consultations?/gi,'Design Studio').replace(/Digital Consultation/gi,'Design Studio');
   document.querySelectorAll('h1,.consult-kicker,.ey,a').forEach(el=>{
     if(el.childElementCount>0) return;
     const t=el.textContent||'';
     if(/Digital Consultations?/i.test(t)) el.textContent=t.replace(/Digital Consultations?/gi,'Design Studio');
     if(/^← Consultations\s*$/i.test(t.trim())) el.textContent='← Design Studio';
   });

   if(path==='/consultations'){
     const main=document.querySelector('.consult-wrap,main');
     const header=main?.querySelector('.consult-brandbar,header');
     if(main&&header&&!main.querySelector('.ec-design-hero')){
       const hero=document.createElement('section');
       hero.className='ec-design-hero';
       hero.innerHTML=`<img src="${HERO}" alt="Design Studio artist bringing a customer's tattoo vision to life"><div class="ec-design-hero-copy"><div class="ey consult-kicker">Empty Chair Design Studio</div><h2>Bring the vision to life.</h2><p>Message, refine the design, approve revisions, quote, deposit, and book — all in one conversation.</p></div>`;
       header.insertAdjacentElement('afterend',hero);
     }
   }

   if(/^\/consultations\/[^/]+$/.test(path)){
     document.body.classList.add('ec-design-studio-thread');
     document.querySelectorAll('.consult-msg.outbound,.msg.outbound').forEach(msg=>{
       if(msg.querySelector('.ec-artist-bubble-avatar')) return;
       const avatar=document.createElement('img');
       avatar.className='ec-artist-bubble-avatar';
       avatar.src=HEAD;
       avatar.alt='Design Studio artist';
       msg.appendChild(avatar);
     });
   }
 };
 if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
</script>
"""


@core.app.middleware("http")
async def brand_design_studio(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/consultations") or "text/html" not in response.headers.get("content-type", "").lower():
        return response
    chunks=[]
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    body=b"".join(chunks).decode("utf-8",errors="replace")
    body=body.replace("Digital Consultations", "Design Studio").replace("Digital Consultation", "Design Studio")
    if "ec-design-studio-brand" not in body:
        body=body.replace("</body>",_DESIGN_STUDIO_UI+"</body>",1)
    headers=dict(response.headers)
    headers.pop("content-length",None)
    return Response(content=body,status_code=response.status_code,headers=headers,media_type="text/html",background=response.background)
