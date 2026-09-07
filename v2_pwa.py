"""Phone/PWA surface for Empty Chair 2.0.

No legacy product code. This module only adds install/update behavior and keeps the
2.0 phone surface cache-safe. Google and Apple Calendar remain first-class setup options.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

import v2_app as core

app = core.app

PWA_VERSION = "2.0.3"
APPLE_TOUCH_ICON = "static/apple-touch-icon.png"


@app.middleware("http")
async def pwa_headers(request: Request, call_next):
    """Make installed copies update aggressively instead of hanging onto stale 1.x UI."""
    response = await call_next(request)
    path = request.url.path
    if path in {"/", "/manifest.webmanifest", "/sw.js", "/icon.svg", "/apple-touch-icon.png", "/install"} or path.startswith("/setup") or path.startswith("/o/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    response.headers["X-Empty-Chair-Version"] = PWA_VERSION
    return response


@app.middleware("http")
async def pwa_overrides(request: Request, call_next):
    path = request.url.path
    if path == "/manifest.webmanifest":
        return JSONResponse(
            {
                "id": "/",
                "name": "Empty Chair",
                "short_name": "Empty Chair",
                "description": "When they cancel, we fill the chair.",
                "start_url": "/?pwa=2.0.3",
                "scope": "/",
                "display": "standalone",
                "orientation": "portrait",
                "background_color": core.BG,
                "theme_color": core.BG,
                "icons": [
                    {
                        "src": "/icon.svg?v=2.0.3",
                        "sizes": "any",
                        "type": "image/svg+xml",
                        "purpose": "any maskable",
                    }
                ],
            },
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-store"},
        )

    if path == "/apple-touch-icon.png":
        return FileResponse(APPLE_TOUCH_ICON, media_type="image/png", headers={"Cache-Control": "no-store"})

    if path == "/sw.js":
        js = f'''const VERSION="empty-chair-{PWA_VERSION}";
self.addEventListener("install",event=>self.skipWaiting());
self.addEventListener("activate",event=>event.waitUntil((async()=>{{
  const keys=await caches.keys();
  await Promise.all(keys.map(k=>caches.delete(k)));
  await self.clients.claim();
}})()));
self.addEventListener("fetch",event=>{{
  if(event.request.method!=="GET") return;
  event.respondWith(fetch(event.request,{{cache:"no-store"}}).catch(()=>new Response("EMPTY CHAIR // OFFLINE",{{status:503,headers:{{"Content-Type":"text/plain"}}}})));
}});'''
        return Response(js, media_type="application/javascript", headers={"Cache-Control": "no-store"})

    if path == "/setup/calendar" and request.method == "GET":
        artist = core.current_artist(request)
        if not artist:
            return RedirectResponse("/setup")
        acct = core.one("SELECT * FROM calendar_accounts WHERE artist_id=?", (artist["id"],))
        if acct and (acct["provider"] == "google" or (acct["provider"] == "apple" and acct.get("apple_calendar_url"))):
            return core.page(
                "Calendar",
                f'''<div class="center"><h1 class="bright">CALENDAR CONNECTED [✓]</h1><p>{acct["provider"].upper()}</p><a class="button" href="/setup/payment">NEXT</a></div>''',
            )
        google = '<a class="button" href="/auth/google/start">[ G ] GOOGLE CALENDAR</a>' if core.GOOGLE_CLIENT_ID else '<div class="button quiet">[ G ] GOOGLE // NEEDS CONFIG</div>'
        apple = '<a class="button" href="/setup/apple">[ A ] APPLE CALENDAR</a>'
        return core.page(
            "Calendar",
            f'''<h1>WHERE DO YOUR APPOINTMENTS LIVE?</h1><div class="stack">{google}{apple}</div>''',
        )

    return await call_next(request)


@app.get("/install", response_class=HTMLResponse)
def install_page():
    body = '''
<div class="center">
  <h1 class="bright">EMPTY CHAIR 2.0</h1>
  <p>PHONE TEST BUILD</p>
  <div class="space"></div>
  <p class="dim">iPhone</p>
  <p>Safari → Share → Add to Home Screen</p>
  <div class="space"></div>
  <p class="dim">Already installed?</p>
  <p>Open it once from Safari first. This build clears old app caches automatically.</p>
  <div class="space"></div>
  <a class="button" href="/">OPEN EMPTY CHAIR</a>
</div>
'''
    head = '''<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=2.0.3"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black"><meta name="apple-mobile-web-app-title" content="Empty Chair">'''
    script = '''<script>
if("serviceWorker" in navigator){
  navigator.serviceWorker.register("/sw.js",{updateViaCache:"none"}).then(r=>r.update()).catch(()=>{});
}
</script>'''
    return core.page("Install", body, head=head, script=script, chair=True)


@app.middleware("http")
async def register_worker(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        return response
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    body = b"".join(chunks)
    head_marker = b"</head>"
    icon_link = b'<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=2.0.3"></head>'
    if head_marker in body and b'apple-touch-icon' not in body:
        body = body.replace(head_marker, icon_link, 1)
    body_marker = b"</body>"
    worker = b'''<script>if("serviceWorker" in navigator){navigator.serviceWorker.register("/sw.js",{updateViaCache:"none"}).then(r=>r.update()).catch(()=>{});}</script></body>'''
    if body_marker in body:
        body = body.replace(body_marker, worker, 1)
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return Response(body, status_code=response.status_code, headers=headers, media_type="text/html")
