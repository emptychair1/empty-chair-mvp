import json
from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import app as core

app = core.app


def ensure_concierge_table():
    conn = core.connect()
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS concierge_settings (
            shop_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            introduction_mode INTEGER NOT NULL DEFAULT 1,
            remember_context INTEGER NOT NULL DEFAULT 1,
            ask_before_contact INTEGER NOT NULL DEFAULT 1,
            max_questions INTEGER NOT NULL DEFAULT 4,
            tone TEXT NOT NULL DEFAULT 'quiet',
            learned_context TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        )
        """,
    )
    conn.commit()
    conn.close()


def get_concierge_settings(shop_id):
    ensure_concierge_table()
    conn = core.connect()
    row = core.db_fetchone(
        conn,
        "SELECT * FROM concierge_settings WHERE shop_id = ? LIMIT 1",
        (shop_id,),
    )
    if not row:
        core.db_execute(
            conn,
            """
            INSERT INTO concierge_settings(
                shop_id, enabled, introduction_mode, remember_context,
                ask_before_contact, max_questions, tone, learned_context, updated_at
            ) VALUES (?, 1, 1, 1, 1, 4, 'quiet', '{}', ?)
            """,
            (shop_id, core.now_iso()),
        )
        conn.commit()
        row = core.db_fetchone(
            conn,
            "SELECT * FROM concierge_settings WHERE shop_id = ? LIMIT 1",
            (shop_id,),
        )
    conn.close()
    return row


@app.get('/concierge/settings', response_class=HTMLResponse)
def concierge_settings_page(request: Request, saved: int = 0):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    shop = core.db_fetchone(
        conn,
        "SELECT * FROM shops WHERE id = ? LIMIT 1",
        (user['shop_id'],),
    )
    conn.close()
    settings = get_concierge_settings(user['shop_id'])
    return core.templates.TemplateResponse(
        request=request,
        name='concierge_settings.html',
        context={
            'user': user,
            'shop': shop,
            'settings': settings,
            'saved': bool(saved),
        },
    )


@app.post('/concierge/settings')
def update_concierge_settings(
    request: Request,
    enabled: str = Form(''),
    introduction_mode: str = Form(''),
    remember_context: str = Form(''),
    ask_before_contact: str = Form(''),
    max_questions: int = Form(4),
    tone: str = Form('quiet'),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    ensure_concierge_table()
    max_questions = max(1, min(int(max_questions or 4), 8))
    tone = tone if tone in {'quiet', 'warm', 'direct'} else 'quiet'
    conn = core.connect()
    existing = core.db_fetchone(
        conn,
        "SELECT learned_context FROM concierge_settings WHERE shop_id = ? LIMIT 1",
        (user['shop_id'],),
    )
    learned_context = existing['learned_context'] if existing else '{}'
    core.db_execute(
        conn,
        """
        INSERT INTO concierge_settings(
            shop_id, enabled, introduction_mode, remember_context,
            ask_before_contact, max_questions, tone, learned_context, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(shop_id) DO UPDATE SET
            enabled=excluded.enabled,
            introduction_mode=excluded.introduction_mode,
            remember_context=excluded.remember_context,
            ask_before_contact=excluded.ask_before_contact,
            max_questions=excluded.max_questions,
            tone=excluded.tone,
            updated_at=excluded.updated_at
        """,
        (
            user['shop_id'],
            1 if enabled else 0,
            1 if introduction_mode else 0,
            1 if remember_context else 0,
            1 if ask_before_contact else 0,
            max_questions,
            tone,
            learned_context,
            core.now_iso(),
        ),
    )
    conn.commit()
    conn.close()
    core.event('concierge.settings_changed', 'shop', user['shop_id'])
    return RedirectResponse('/concierge/settings?saved=1', status_code=303)
