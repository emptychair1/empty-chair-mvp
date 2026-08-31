"""Presentation-only Design Studio branding for consultation pages.

No database or network work occurs at import time. Existing consultation,
quote, revision, payment, and booking behavior remains unchanged.
"""
from fastapi import Request
from fastapi.responses import Response

import app as core

HERO = "/static/733F1C1D-4E3A-4898-8B42-3C7E245DC754.png"
PAINTER_HEAD = "/static/196D271D-A614-4C34-9A62-AE9D2E18DC15.png"

_DESIGN_STUDIO_ASSETS = f"""
<style id='ec-design-studio-branding'>
.ec-design-studio-hero{{position:relative;overflow:hidden;margin:4px 0 20px;border:1px solid #30362c;border-radius:16px;background:#090b09;min-height:260px;box-shadow:0 18px 42px rgba(0,0,0,.28)}}
.ec-design-studio-hero img{{display:block;width:100%;height:clamp(250px,32vw,390px);object-fit:cover;object-position:center}}
.ec-design-studio-hero:after{{content:'';position:absolute;inset:0;background:linear-gradient(90deg,rgba(6,7,6,.58),transparent 52%),linear-gradient(0deg,rgba(6,7,6,.45),transparent 45%);pointer-events:none}}
.ec-design-studio-hero-copy{{position:absolute;z-index:2;left:22px;bottom:20px;max-width:430px;text-shadow:0 2px 16px #000}}
.ec-design-studio-hero-copy .ey{{margin-bottom:7px}}
.ec-design-studio-hero-copy h2{{margin:0;font-family:'Bangers',Impact,sans-serif;font-size:42px;font-weight:400;line-height:.95;letter-spacing:.015em;color:#f2ecde}}
.ec-design-studio-hero-copy p{{margin:8px 0 0;color:#d7ddd1;font-size:13px;line-height:1.45}}
.ec-design-studio-outbound{{display:flex;justify-content:flex-end;align-items:flex-end;gap:8px;align-self:flex-end;max-width:88%}}
.ec-design-studio-outbound .msg.outbound{{align-self:auto;max-width:100%;margin:0}}
.ec-painter-head{{width:34px;height:34px;min-width:34px;border-radius:50%;object-fit:cover;border:1px solid #566143;background:#0c0f0c;box-shadow:0 2px 8px rgba(0,0,0,.35)}}
@media(max-width:620px){{.ec-design-studio-hero{{min-height:210px;margin-bottom:14px}}.ec-design-studio-hero img{{height:230px}}.ec-design-studio-hero-copy{{left:15px;right:15px;bottom:14px}}.ec-design-studio-hero-copy h2{{font-size:34px}}.ec-design-studio-hero-copy p{{font-size:12px}}.ec-design-studio-outbound{{max-width:92%;gap:6px}}.ec-painter-head{{width:30px;height:30px;min-width:30px}}}}
</style>
<script id='ec-design-studio-js'>
(()=>{{
 const HEAD={PAINTER_HEAD!r};
 const boot=()=>{{
   document.querySelectorAll('.msg.outbound').forEach(msg=>{{
     if(msg.closest('.ec-design-studio-outbound')) return;
     const row=document.createElement('div');
     row.className='ec-design-studio-outbound';
     msg.parentNode.insertBefore(row,msg);
     row.appendChild(msg);
     const avatar=document.createElement('img');
     avatar.className='ec-painter-head';
     avatar.src=HEAD;
     avatar.alt='Design Studio artist';
     row.appendChild(avatar);
   }});
 }};
 if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{{once:true}}); else boot();
}})();
</script>
"""


@core.app.middleware("http")
async def brand_design_studio(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path.rstrip("/") or "/"
    if not path.startswith("/consultations") or "text/html" not in response.headers.get("content-type", "").lower():
        return response

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    body = b"".join(chunks).decode("utf-8", errors="replace")

    # User-facing rename only; URLs stay stable to avoid breaking integrations.
    body = body.replace("Digital Consultations", "Design Studio")
    body = body.replace("Digital Consultation", "Design Studio")
    body = body.replace("digital consultation", "design studio conversation")

    if path == "/consultations" and "ec-design-studio-hero" not in body:
        hero = f"""<section class='ec-design-studio-hero'><img src='{HERO}' alt='Design Studio artist bringing a customer tattoo idea to life'><div class='ec-design-studio-hero-copy'><div class='ey consult-kicker'>Design Studio</div><h2>Bring the vision to life.</h2><p>Talk through the idea, exchange references, manage revisions, quote the work, and move the customer toward a booked tattoo.</p></div></section>"""
        marker = "</header>"
        if marker in body:
            body = body.replace(marker, marker + hero, 1)

    if "ec-design-studio-branding" not in body:
        body = body.replace("</body>", _DESIGN_STUDIO_ASSETS + "</body>", 1)

    headers = dict(response.headers)
    headers.pop("content-length", None)
    return Response(content=body, status_code=response.status_code, headers=headers, media_type="text/html", background=response.background)
