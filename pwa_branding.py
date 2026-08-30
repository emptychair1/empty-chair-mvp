"""PWA + favicon branding for Empty Chair."""

from fastapi.responses import JSONResponse, RedirectResponse

import app as core

ICON_PATH = "/static/app-icon.png?v=1"


@core.app.get("/manifest.webmanifest")
def pwa_manifest():
    return JSONResponse(
        {
            "name": "Empty Chair",
            "short_name": "Empty Chair",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#b1ff00",
            "theme_color": "#b1ff00",
            "icons": [
                {
                    "src": ICON_PATH,
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                }
            ],
        },
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@core.app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse(url=ICON_PATH, status_code=307)


@core.app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon():
    return RedirectResponse(url=ICON_PATH, status_code=307)
