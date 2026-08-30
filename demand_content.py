"""Content inventory for Demand Engine acquisition assets."""
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core


def _ensure_tables(conn):
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS demand_content_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id TEXT NOT NULL,
            title TEXT NOT NULL,
            asset_type TEXT NOT NULL DEFAULT 'flash',
            theme TEXT NOT NULL DEFAULT 'other',
            status TEXT NOT NULL DEFAULT 'unused',
            source_name TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    conn.commit()


@core.app.get("/demand-acquisition/content", response_class=HTMLResponse)
def content_library(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        assets = core.db_fetchall(
            conn,
            "SELECT * FROM demand_content_assets WHERE shop_id=? ORDER BY created_at DESC, id DESC",
            (user["shop_id"],),
        )
    finally:
        conn.close()
    counts = {"unused": 0, "queued": 0, "published": 0}
    for row in assets:
        status = row["status"] if row["status"] in counts else "unused"
        counts[status] += 1
    return core.templates.TemplateResponse(
        request=request,
        name="demand_content.html",
        context={"user": user, "assets": assets, "counts": counts},
        headers={"Cache-Control": "no-store"},
    )


@core.app.post("/demand-acquisition/content")
async def create_content_asset(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    form = await request.form()
    title = str(form.get("title") or "").strip()
    if not title:
        return RedirectResponse("/demand-acquisition/content", status_code=303)
    asset_type = str(form.get("asset_type") or "flash").strip()
    theme = str(form.get("theme") or "other").strip()
    source_name = str(form.get("source_name") or "").strip()
    notes = str(form.get("notes") or "").strip()
    conn = core.connect()
    try:
        _ensure_tables(conn)
        core.db_execute(
            conn,
            "INSERT INTO demand_content_assets (shop_id,title,asset_type,theme,status,source_name,notes) VALUES (?,?,?,?,?,?,?)",
            (user["shop_id"], title, asset_type, theme, "unused", source_name, notes),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/demand-acquisition/content", status_code=303)


@core.app.post("/demand-acquisition/content/{asset_id}/status")
async def update_content_status(asset_id: int, request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    form = await request.form()
    status = str(form.get("status") or "unused").strip().lower()
    if status not in {"unused", "queued", "published"}:
        status = "unused"
    conn = core.connect()
    try:
        _ensure_tables(conn)
        core.db_execute(
            conn,
            "UPDATE demand_content_assets SET status=? WHERE id=? AND shop_id=?",
            (status, asset_id, user["shop_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/demand-acquisition/content", status_code=303)
