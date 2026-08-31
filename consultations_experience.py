"""Branded Digital Consultations shell + lightweight unread indicator.

No database or network work occurs at import time. The unread endpoint is read-only,
and the middleware only decorates consultation HTML responses.
"""
from fastapi import Request
from fastapi.responses import JSONResponse, Response

import app as core


@core.app.get("/api/consultations/unread-count")
def consultation_unread_count(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return JSONResponse({"count": 0}, status_code=401, headers={"Cache-Control": "no-store"})
    conn = core.connect()
    try:
        row = core.db_fetchone(conn, """
            SELECT COUNT(*) AS n
            FROM concierge_conversations x
            WHERE x.shop_id=? AND x.status='open'
              AND EXISTS (
                SELECT 1 FROM concierge_messages latest
                WHERE latest.conversation_id=x.id
                  AND latest.direction='inbound'
                  AND latest.created_at=(SELECT MAX(m.created_at) FROM concierge_messages m WHERE m.conversation_id=x.id)
              )
        """, (user["shop_id"],))
        return JSONResponse({"count": int(row["n"] if row else 0)}, headers={"Cache-Control": "no-store"})
    except Exception:
        return JSONResponse({"count": 0}, headers={"Cache-Control": "no-store"})
    finally:
        conn.close()


_CONSULTATION_AVATAR_SCRIPT = """
<script>
(()=>{
  const decorate=()=>{
    const avatars=window.EmptyChairAvatar;
    const avatarSrc=(name)=>avatars&&avatars.src?avatars.src(name):'/static/profile-16.png?v=5';

    document.querySelectorAll('.consult-thread').forEach(thread=>{
      if(thread.dataset.avatarReady==='1') return;
      const nameEl=thread.querySelector('strong');
      if(!nameEl) return;
      const name=(nameEl.textContent||'').trim();
      if(!name) return;
      const preview=thread.querySelector('span');
      const meta=thread.querySelector('small');
      const main=document.createElement('span');
      main.className='consult-thread-main';
      nameEl.classList.add('consult-thread-name');
      if(preview) preview.classList.add('consult-thread-preview');
      if(meta) meta.classList.add('consult-thread-meta');
      nameEl.parentNode.insertBefore(main,nameEl);
      main.appendChild(nameEl);
      if(preview) main.appendChild(preview);
      if(meta) main.appendChild(meta);
      const img=document.createElement('img');
      img.className='consult-user-avatar person-avatar';
      img.dataset.name=name;
      img.alt='';
      img.src=avatarSrc(name);
      thread.insertBefore(img,main);
      thread.dataset.avatarReady='1';
    });

    if(location.pathname!='/consultations'){
      const header=document.querySelector('.consult-brandbar');
      const info=header?.querySelector(':scope > div');
      const nameEl=info?.querySelector('h1');
      if(header&&info&&nameEl&&!header.querySelector('.consult-user-avatar')){
        const name=(nameEl.textContent||'').trim();
        const wrap=document.createElement('div');
        wrap.className='consult-person-identity';
        const img=document.createElement('img');
        img.className='consult-user-avatar consult-user-avatar-large person-avatar';
        img.dataset.name=name;
        img.alt='';
        img.src=avatarSrc(name);
        header.insertBefore(wrap,info);
        wrap.appendChild(img);
        wrap.appendChild(info);
      }
    }
  };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',decorate,{once:true}); else decorate();
})();
</script>
"""


@core.app.middleware("http")
async def brand_consultation_pages(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/consultations") or "text/html" not in response.headers.get("content-type", "").lower():
        return response
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    body = b"".join(chunks).decode("utf-8", errors="replace")
    if "consultations-brand.css" not in body:
        body = body.replace(
            "</head>",
            "<script src='/static/demo-avatar.js?v=4' defer></script><link rel='stylesheet' href='/static/consultations-brand.css?v=3'></head>",
            1,
        )
    body = body.replace("<body>", "<body class='consult-shell'>", 1)
    body = body.replace("<main>", "<main class='consult-wrap'>", 1)
    body = body.replace("<header>", "<header class='consult-brandbar'>", 1)
    body = body.replace("<h1>", "<h1 class='consult-title'>")
    body = body.replace("class='ey'", "class='ey consult-kicker'")
    body = body.replace("class='thread'", "class='thread consult-thread'")
    body = body.replace("class='empty'", "class='empty consult-empty'")
    body = body.replace("class='chat'", "class='chat consult-chat'")
    body = body.replace("class='msg inbound'", "class='msg inbound consult-msg'")
    body = body.replace("class='msg outbound'", "class='msg outbound consult-msg'")
    body = body.replace("<form method='post' action='/consultations/", "<form class='consult-compose' method='post' action='/consultations/", 1)
    body = body.replace("<button type='submit'>Send SMS</button>", "<button class='consult-send' type='submit'>Send SMS</button>", 1)
    body = body.replace("</body>", _CONSULTATION_AVATAR_SCRIPT + "</body>", 1)
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return Response(content=body, status_code=response.status_code, headers=headers, media_type="text/html", background=response.background)
