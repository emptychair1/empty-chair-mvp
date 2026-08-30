"""Instagram Content Studio for Demand acquisition assets."""
import hashlib
import os
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import app as core


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_UPLOAD_FILES = 30


def _ensure_column(conn, column, ddl="TEXT"):
    if getattr(core, "USE_POSTGRES", False):
        core.db_execute(conn, f"ALTER TABLE demand_content_assets ADD COLUMN IF NOT EXISTS {column} {ddl}")
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(demand_content_assets)").fetchall()}
    if column not in columns:
        sqlite_ddl = "BLOB" if ddl.upper() == "BYTEA" else ddl
        core.db_execute(conn, f"ALTER TABLE demand_content_assets ADD COLUMN {column} {sqlite_ddl}")


def _ensure_tables(conn):
    id_ddl = "BIGSERIAL PRIMARY KEY" if getattr(core, "USE_POSTGRES", False) else "INTEGER PRIMARY KEY AUTOINCREMENT"
    core.db_execute(conn, f"""
        CREATE TABLE IF NOT EXISTS demand_content_assets (
            id {id_ddl},
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
    for column in ("image_url", "instagram_hook", "instagram_caption", "instagram_cta", "image_mime", "image_sha256"):
        _ensure_column(conn, column)
    _ensure_column(conn, "image_data", "BYTEA")
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


def _clean_title(filename):
    stem = os.path.splitext(os.path.basename(filename or "portfolio image"))[0]
    return stem.replace("_", " ").replace("-", " ").strip() or "Portfolio image"


@core.app.get("/demand-acquisition/content", response_class=HTMLResponse)
def content_library(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        assets = [dict(r) for r in core.db_fetchall(conn, "SELECT id,shop_id,title,asset_type,theme,status,source_name,notes,created_at,image_url,image_mime,image_sha256,instagram_hook,instagram_caption,instagram_cta FROM demand_content_assets WHERE shop_id=? ORDER BY created_at DESC, id DESC", (user["shop_id"],))]
    finally:
        conn.close()
    counts = {"unused": 0, "queued": 0, "published": 0}
    for asset in assets:
        status = asset.get("status") if asset.get("status") in counts else "unused"
        counts[status] += 1
        if asset.get("image_mime"):
            asset["image_url"] = f"/demand-acquisition/content/{asset['id']}/image"
        asset["draft_hook"], asset["draft_caption"], asset["draft_cta"] = _draft_for(asset)
    return core.templates.TemplateResponse(request=request, name="demand_content.html", context={"user": user, "assets": assets, "counts": counts, "uploaded": request.query_params.get("uploaded"), "skipped": request.query_params.get("skipped"), "upload_error": request.query_params.get("error")}, headers={"Cache-Control": "no-store"})


@core.app.get("/demand-acquisition/content/{asset_id}/image")
def content_asset_image(asset_id: int, request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        row = core.db_fetchone(conn, "SELECT image_data,image_mime FROM demand_content_assets WHERE id=? AND shop_id=?", (asset_id, user["shop_id"]))
    finally:
        conn.close()
    if not row or not row["image_data"]:
        return Response(status_code=404)
    data = bytes(row["image_data"])
    return Response(content=data, media_type=row["image_mime"] or "application/octet-stream", headers={"Cache-Control": "private, max-age=3600"})


@core.app.post("/demand-acquisition/content/upload")
async def upload_content_images(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    form = await request.form()
    files = list(form.getlist("images"))[:MAX_UPLOAD_FILES]
    asset_type = str(form.get("asset_type") or "finished_tattoo").strip()
    theme = str(form.get("theme") or "other").strip()
    uploaded = 0
    skipped = 0
    error = ""
    conn = core.connect()
    try:
        _ensure_tables(conn)
        for upload in files:
            filename = str(getattr(upload, "filename", "") or "").strip()
            mime = str(getattr(upload, "content_type", "") or "").lower()
            if not filename:
                continue
            if mime not in ALLOWED_IMAGE_TYPES:
                skipped += 1
                error = "Use JPG, PNG, WebP, or GIF images."
                continue
            data = await upload.read(MAX_UPLOAD_BYTES + 1)
            if not data or len(data) > MAX_UPLOAD_BYTES:
                skipped += 1
                error = "Each image must be 12 MB or smaller."
                continue
            digest = hashlib.sha256(data).hexdigest()
            existing = core.db_fetchone(conn, "SELECT id FROM demand_content_assets WHERE shop_id=? AND image_sha256=?", (user["shop_id"], digest))
            if existing:
                skipped += 1
                continue
            core.db_execute(conn, """INSERT INTO demand_content_assets
                (shop_id,title,asset_type,theme,status,source_name,notes,image_url,image_data,image_mime,image_sha256)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                user["shop_id"], _clean_title(filename), asset_type, theme, "unused", filename, "", "", data, mime, digest
            ))
            uploaded += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    params = {"uploaded": uploaded, "skipped": skipped}
    if error:
        params["error"] = error
    return RedirectResponse("/demand-acquisition/content?" + urlencode(params), status_code=303)


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
