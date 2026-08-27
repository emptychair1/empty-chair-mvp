import json
import os
import urllib.error
import urllib.parse
import urllib.request

from fastapi import Request
from fastapi.responses import HTMLResponse, Response, JSONResponse

import app as core
import m4_runtime
import m4_founder_simulation_engine as founder_engine

app = core.app
M4_VOICE_ID = os.getenv("M4_ELEVENLABS_VOICE_ID", "Ss7hQAiJNG6a81OU5k51")
M4_VOICE_MODEL = os.getenv("M4_ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")


@app.get('/m4', response_class=HTMLResponse)
def m4_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    shop = core.db_fetchone(conn, 'SELECT * FROM shops WHERE id=? LIMIT 1', (user['shop_id'],))
    customers = [dict(r) for r in core.db_fetchall(conn, 'SELECT * FROM customers WHERE shop_id=?', (user['shop_id'],))]
    openings = [dict(r) for r in core.db_fetchall(conn, "SELECT o.*,a.name AS artist_name FROM openings o JOIN artists a ON a.id=o.artist_id WHERE o.shop_id=? AND o.status IN ('OPEN','RECOVERY_ACTIVE','NO_RECOVERY') ORDER BY o.date,o.start_time", (user['shop_id'],))]
    conn.close()
    live = openings[0] if openings else None
    ranked = m4_runtime.rank(customers, live, 10) if live else []
    consented = sum(1 for c in customers if c.get('communication_consent'))
    expected = sum(r['expected_value'] for r in ranked)
    avg_conf = sum(r['confidence'] for r in ranked) / len(ranked) if ranked else 0
    styles = {}
    for c in customers:
        if not c.get('communication_consent'):
            continue
        for style in str(c.get('preferred_styles') or '').split(','):
            style = style.strip()
            if style:
                styles[style] = styles.get(style, 0) + 1
    demand = sorted(styles.items(), key=lambda x: x[1], reverse=True)[:8]
    recommendation = None
    try:
        recommendation = founder_engine.latest_recommendation(user['shop_id'])
    except Exception:
        recommendation = None
    return core.templates.TemplateResponse(
        request=request,
        name='m4.html',
        context={
            'user': user,
            'shop': shop,
            'opening': live,
            'ranked': ranked,
            'consented': consented,
            'expected': expected,
            'avg_conf': avg_conf,
            'demand': demand,
            'model': m4_runtime.MODEL,
            'recommendation': recommendation,
            'm4_voice_id': M4_VOICE_ID,
        },
    )


@app.get('/api/m4/recommendation/audio')
def m4_recommendation_audio(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({'error': 'Sign in first.'}, status_code=401)
    try:
        recommendation = founder_engine.latest_recommendation(user['shop_id'])
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=503)
    if not recommendation:
        return JSONResponse({'error': 'M4 has no recommendation to speak yet.'}, status_code=404)
    if not ELEVENLABS_API_KEY:
        return JSONResponse({'error': 'ELEVENLABS_API_KEY is not configured.'}, status_code=503)

    voice_id = recommendation.get('voice_id') or M4_VOICE_ID
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{urllib.parse.quote(voice_id)}?output_format=mp3_44100_128"
    payload = {
        'text': recommendation['recommendation_text'],
        'model_id': M4_VOICE_MODEL,
        'voice_settings': {
            'stability': 0.34,
            'similarity_boost': 0.76,
            'style': 0.48,
            'use_speaker_boost': True,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'xi-api-key': ELEVENLABS_API_KEY, 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            audio = response.read()
        return Response(
            content=audio,
            media_type='audio/mpeg',
            headers={'Cache-Control': 'no-store, no-cache, must-revalidate'},
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        return JSONResponse({'error': f'ElevenLabs HTTP {exc.code}', 'detail': detail[:800]}, status_code=503)
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=503)
