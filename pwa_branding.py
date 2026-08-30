"""PWA + favicon branding for Empty Chair."""

from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

import app as core

ICON_192 = "/static/pwa-192.webp?v=2"
ICON_512 = "/static/app-icon.png?v=2"
FAVICON = "/static/favicon.png?v=2"


@core.app.get("/manifest.webmanifest")
def pwa_manifest():
    return JSONResponse(
        {
            "name": "Empty Chair",
            "short_name": "Empty Chair",
            "description": "Empty Chair tattoo studio demand and operations.",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#080a08",
            "theme_color": "#b1ff00",
            "icons": [
                {
                    "src": ICON_192,
                    "sizes": "192x192",
                    "type": "image/webp",
                    "purpose": "any",
                },
                {
                    "src": ICON_512,
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ],
        },
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@core.app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Service-Worker-Allowed": "/",
        },
    )


@core.app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse(url=FAVICON, status_code=307)


@core.app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon():
    return RedirectResponse(url=ICON_512, status_code=307)
