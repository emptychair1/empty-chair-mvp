"""Instagram Content Studio for Demand acquisition assets."""
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core


def _ensure_tables(conn):
    core.db_execute(conn, """
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
    """)
    for statement in (
        "ALTER TABLE demand_content_assets ADD COLUMN image_url TEXT",
        "ALTER TABLE demand_content_assets ADD COLUMN instagram_hook TEXT",
        "ALTER TABLE demand_content_assets ADD COLUMN instagram_caption TEXT",
        "ALTER TABLE demand_content_assets ADD COLUMN instagram_cta TEXT",
    ):
        try:
            core.db_execute(conn, statement)
        except Exception:
            pass
    conn.commit()


def _draft_for(asset):
    title = str(asset.get("title") or "this piece")
    theme = str(asset.get("theme") or "other").replace("_", " ")
    hook = str(asset.get("instagram_hook") or "").strip()
    caption = str(asset.get("instagram_caption") or "").strip()
    cta = str(asset.get("instagram_cta") or "").strip()
    if not hook:
        hook = f"Would you wear {title.lower()}?"
    if not caption:
        caption = f"{title}. {theme.title()} work from my portfolio. I want to do more pieces in this direction in Athens."
    if not cta:
        cta = "DM me with the word TATTOO and I’ll send availability."
    return hook, caption, cta


@core.app.get("/demand-acquisition/content", response_class=HTMLResponse)
def content_library(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        assets = [dict(r) for r in core.db_fetchall(conn, "SELECT * FROM demand_content_assets WHERE shop_id=? ORDER BY created_at DESC, id DESC", (user["shop_id"],))]
    finally:
        conn.close()
    counts = {"unused": 0, "queued": 0, "published": 0}
    for asset in assets:
        status = asset.get("status") if asset.get("status") in counts else "unused"
        counts[status] += 1
        asset["draft_hook"], asset["draft_caption"], asset["draft_cta"] = _draft_for(asset)
    return core.templates.TemplateResponse(request=request, name="demand_content.html", context={"user": user, "assets": assets, "counts": counts}, headers={"Cache-Control": "no-store"})


@core.app.post("/demand-acquisition/content")
async def create_content_asset(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    form = await request.form()
    title = str(form.get("title") or "").strip()
    if not title:
        return RedirectResponse("/demand-acquisition/content", status_code=303)
    values = (
        user["shop_id"], title, str(form.get("asset_type") or "flash").strip(),
        str(form.get("theme") or "other").strip(), "unused",
        str(form.get("source_name") or "").strip(), str(form.get("notes") or "").strip(),
        str(form.get("image_url") or "").strip(),
    )
    conn = core.connect()
    try:
        _ensure_tables(conn)
        core.db_execute(conn, "INSERT INTO demand_content_assets (shop_id,title,asset_type,theme,status,source_name,notes,image_url) VALUES (?,?,?,?,?,?,?,?)", values)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/demand-acquisition/content", status_code=303)


@core.app.post("/demand-acquisition/content/{asset_id}/draft")
async def save_instagram_draft(asset_id: int, request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    form = await request.form()
    hook = str(form.get("instagram_hook") or "").strip()
    caption = str(form.get("instagram_caption") or "").strip()
    cta = str(form.get("instagram_cta") or "").strip()
    status = str(form.get("status") or "queued").strip().lower()
    if status not in {"unused", "queued", "published"}:
        status = "queued"
    conn = core.connect()
    try:
        _ensure_tables(conn)
        core.db_execute(conn, "UPDATE demand_content_assets SET instagram_hook=?,instagram_caption=?,instagram_cta=?,status=? WHERE id=? AND shop_id=?", (hook, caption, cta, status, asset_id, user["shop_id"]))
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
        core.db_execute(conn, "UPDATE demand_content_assets SET status=? WHERE id=? AND shop_id=?", (status, asset_id, user["shop_id"]))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/demand-acquisition/content", status_code=303)
