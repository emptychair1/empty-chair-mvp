import base64
import re

from fastapi.responses import FileResponse, JSONResponse, Response

import app as core

app = core.app

ICON_SVG_PATH = 'static/icons/empty-chair-mascot-favicon.svg'
ICON_SVG_URL = '/static/icons/empty-chair-mascot-favicon.svg'


def _icon_png_bytes() -> bytes:
    with open(ICON_SVG_PATH, 'r', encoding='utf-8') as handle:
        svg = handle.read()
    match = re.search(r'data:image/png;base64,([^\"]+)', svg)
    if not match:
        raise RuntimeError('Embedded PWA icon PNG is missing.')
    return base64.b64decode(match.group(1))


@app.get('/pwa-icon.png', include_in_schema=False)
def pwa_icon_png():
    return Response(
        content=_icon_png_bytes(),
        media_type='image/png',
        headers={'Cache-Control': 'public, max-age=86400'},
    )


@app.get('/favicon.ico', include_in_schema=False)
def favicon_ico():
    return Response(
        content=_icon_png_bytes(),
        media_type='image/png',
        headers={'Cache-Control': 'public, max-age=86400'},
    )


@app.get('/manifest.webmanifest', include_in_schema=False)
def pwa_manifest():
    return JSONResponse(
        {
            'name': 'Empty Chair',
            'short_name': 'Empty Chair',
            'description': 'Smart cancellation recovery for tattoo studios.',
            'start_url': '/',
            'scope': '/',
            'display': 'standalone',
            'background_color': '#b8ff00',
            'theme_color': '#b8ff00',
            'orientation': 'any',
            'icons': [
                {
                    'src': '/pwa-icon.png',
                    'sizes': '192x192',
                    'type': 'image/png',
                    'purpose': 'any',
                },
                {
                    'src': ICON_SVG_URL,
                    'sizes': 'any',
                    'type': 'image/svg+xml',
                    'purpose': 'any',
                },
                {
                    'src': ICON_SVG_URL,
                    'sizes': 'any',
                    'type': 'image/svg+xml',
                    'purpose': 'maskable',
                },
            ],
        },
        media_type='application/manifest+json',
        headers={'Cache-Control': 'no-cache'},
    )


@app.get('/sw.js', include_in_schema=False)
def pwa_service_worker():
    return FileResponse(
        'static/sw.js',
        media_type='application/javascript',
        headers={
            'Service-Worker-Allowed': '/',
            'Cache-Control': 'no-cache',
        },
    )
