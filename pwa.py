from fastapi.responses import FileResponse, JSONResponse

import empty_chair_legacy_app as core

app = core.app


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
            'background_color': '#070707',
            'theme_color': '#070707',
            'orientation': 'any',
            'icons': [
                {
                    'src': '/static/favicon.png',
                    'type': 'image/png',
                    'purpose': 'any maskable',
                }
            ],
        },
        media_type='application/manifest+json',
        headers={'Cache-Control': 'public, max-age=3600'},
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
