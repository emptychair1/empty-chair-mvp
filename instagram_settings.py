"""Studio UI for managing artist Instagram Professional account connections."""

from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import instagram_integration

app = core.app


@app.get("/settings/instagram", response_class=HTMLResponse)
def instagram_settings_page(request: Request, instagram: str = ""):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        artists = core.db_fetchall(
            conn,
            """
            SELECT id,name,instagram_user_id,instagram_username,
                   instagram_connected_at,instagram_connection_active
            FROM artists
            WHERE shop_id=?
            ORDER BY name
            """,
            (user["shop_id"],),
        )
    finally:
        conn.close()

    return core.templates.TemplateResponse(
        request=request,
        name="instagram_settings.html",
        context={
            "user": user,
            "artists": artists,
            "instagram_configured": instagram_integration.configured(),
            "instagram_message": instagram,
        },
    )
