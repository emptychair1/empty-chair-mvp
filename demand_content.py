"""Instagram Content Studio for Demand acquisition assets."""
import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import app as core


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_UPLOAD_FILES = 30
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
CONTENT_VISION_MODEL = os.getenv("EMPTY_CHAIR_CONTENT_VISION_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"

VISION_PROMPT = """You are the Instagram content strategist inside Empty Chair, a tattoo demand platform.
Analyze the ACTUAL supplied portfolio image. Do not rely on its filename.

Create marketing copy for a tattoo artist based specifically on visible subject matter, composition,
style, linework, color palette, mood, and tattooability. Do not invent details that are not visible.
If the image is a finished tattoo, describe the tattoo rather than making claims about the person.
Never infer or mention identity, race, ethnicity, gender, age, health, or other personal traits.

Return ONLY valid JSON with exactly these keys:
{
  "hook": "3-12 word scroll-stopping hook grounded in the image",
  "caption": "1-3 concise natural sentences that specifically describe why this piece works and invite people who like this direction",
  "cta": "short, low-pressure call to action for someone interested in a similar tattoo",
  "theme": "one of: traditional, weird_playful, dark_occult, nature_animals, pop_culture, other"
}

Avoid generic filler such as 'check out this piece', 'inked', 'tattoo vibes', or 'would you wear this'.
No hashtags unless the image itself makes one clearly relevant. Keep the artist voice confident, specific,
human, and not salesy."""


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
    for column in (
        "image_url", "instagram_hook", "instagram_caption", "instagram_cta",
        "image_mime", "image_sha256", "analysis_status", "analysis_error", "analyzed_at"
    ):
        _ensure_column(conn, column)
    _ensure_column(conn, "image_data", "BYTEA")
    conn.commit()


def _draft_for(asset):
    hook = str(asset.get("instagram_hook") or "").strip()
    caption = str(asset.get("instagram_caption") or "").strip()
    cta = str(asset.get("instagram_cta") or "").strip()
    if not hook:
        hook = "Waiting for image analysis…"
    if not caption:
        caption = "This image has not been visually analyzed yet."
    if not cta:
        cta = "DM me if you want something in this direction."
    return hook, caption, cta


def _clean_title(filename):
    stem = os.path.splitext(os.path.basename(filename or "portfolio image"))[0]
    return stem.replace("_", " ").replace("-", " ").strip() or "Portfolio image"


def _extract_output_text(payload):
    pieces = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                pieces.append(content["text"])
    return "\n".join(pieces).strip()


def _parse_json_text(text):
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def _vision_copy(image_data, image_mime):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    data_url = f"data:{image_mime};base64,{base64.b64encode(bytes(image_data)).decode('ascii')}"
    payload = {
        "model": CONTENT_VISION_MODEL,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": VISION_PROMPT},
                {"type": "input_image", "image_url": data_url},
            ],
        }],
        "max_output_tokens": 700,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=75) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail[:400]}") from exc
    parsed = _parse_json_text(_extract_output_text(result))
    hook = str(parsed.get("hook") or "").strip()
    caption = str(parsed.get("caption") or "").strip()
    cta = str(parsed.get("cta") or "").strip()
    theme = str(parsed.get("theme") or "other").strip()
    allowed_themes = {"traditional", "weird_playful", "dark_occult", "nature_animals", "pop_culture", "other"}
    if theme not in allowed_themes:
        theme = "other"
    if not hook or not caption or not cta:
        raise RuntimeError("Vision response did not contain complete Instagram copy.")
    return hook, caption, cta, theme


@core.app.get("/demand-acquisition/content", response_class=HTMLResponse)
def content_library(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        assets = [dict(r) for r in core.db_fetchall(
            conn,
            """SELECT id,shop_id,title,asset_type,theme,status,source_name,notes,created_at,
            image_url,image_mime,image_sha256,instagram_hook,instagram_caption,instagram_cta,
            analysis_status,analysis_error,analyzed_at
            FROM demand_content_assets WHERE shop_id=? ORDER BY created_at DESC, id DESC""",
            (user["shop_id"],),
        )]
    finally:
        conn.close()
    counts = {"unused": 0, "queued": 0, "published": 0}
    pending_ids = []
    for asset in assets:
        status = asset.get("status") if asset.get("status") in counts else "unused"
        counts[status] += 1
        if asset.get("image_mime"):
            asset["image_url"] = f"/demand-acquisition/content/{asset['id']}/image"
            if not str(asset.get("instagram_hook") or "").strip():
                pending_ids.append(asset["id"])
        asset["draft_hook"], asset["draft_caption"], asset["draft_cta"] = _draft_for(asset)
    return core.templates.TemplateResponse(
        request=request,
        name="demand_content.html",
        context={
            "user": user,
            "assets": assets,
            "counts": counts,
            "uploaded": request.query_params.get("uploaded"),
            "skipped": request.query_params.get("skipped"),
            "upload_error": request.query_params.get("error"),
            "pending_ids": pending_ids,
            "vision_configured": bool(OPENAI_API_KEY),
            "auto_analyze": bool(pending_ids),
        },
        headers={"Cache-Control": "no-store"},
    )


@core.app.get("/demand-acquisition/content/{asset_id}/image")
def content_asset_image(asset_id: int, request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        row = core.db_fetchone(
            conn,
            "SELECT image_data,image_mime FROM demand_content_assets WHERE id=? AND shop_id=?",
            (asset_id, user["shop_id"]),
        )
    finally:
        conn.close()
    if not row or not row["image_data"]:
        return Response(status_code=404)
    data = bytes(row["image_data"])
    return Response(
        content=data,
        media_type=row["image_mime"] or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@core.app.post("/demand-acquisition/content/{asset_id}/analyze")
def analyze_content_asset(asset_id: int, request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return JSONResponse({"ok": False, "error": "Sign in first."}, status_code=401)
    conn = core.connect()
    try:
        _ensure_tables(conn)
        row = core.db_fetchone(
            conn,
            """SELECT id,image_data,image_mime,theme FROM demand_content_assets
            WHERE id=? AND shop_id=?""",
            (asset_id, user["shop_id"]),
        )
        if not row or not row["image_data"]:
            return JSONResponse({"ok": False, "error": "Image not found."}, status_code=404)
        core.db_execute(
            conn,
            "UPDATE demand_content_assets SET analysis_status='analyzing',analysis_error='' WHERE id=? AND shop_id=?",
            (asset_id, user["shop_id"]),
        )
        conn.commit()
        try:
            hook, caption, cta, theme = _vision_copy(row["image_data"], row["image_mime"] or "image/jpeg")
            current_theme = str(row["theme"] or "other")
            final_theme = theme if current_theme == "other" else current_theme
            core.db_execute(
                conn,
                """UPDATE demand_content_assets
                SET instagram_hook=?,instagram_caption=?,instagram_cta=?,theme=?,
                    analysis_status='complete',analysis_error='',analyzed_at=CURRENT_TIMESTAMP
                WHERE id=? AND shop_id=?""",
                (hook, caption, cta, final_theme, asset_id, user["shop_id"]),
            )
            conn.commit()
            return JSONResponse({
                "ok": True,
                "id": asset_id,
                "hook": hook,
                "caption": caption,
                "cta": cta,
                "theme": final_theme,
            })
        except Exception as exc:
            core.db_execute(
                conn,
                "UPDATE demand_content_assets SET analysis_status='error',analysis_error=? WHERE id=? AND shop_id=?",
                (str(exc)[:900], asset_id, user["shop_id"]),
            )
            conn.commit()
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    finally:
        conn.close()


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
            existing = core.db_fetchone(
                conn,
                "SELECT id FROM demand_content_assets WHERE shop_id=? AND image_sha256=?",
                (user["shop_id"], digest),
            )
            if existing:
                skipped += 1
                continue
            core.db_execute(
                conn,
                """INSERT INTO demand_content_assets
                (shop_id,title,asset_type,theme,status,source_name,notes,image_url,image_data,image_mime,
                 image_sha256,analysis_status,analysis_error)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user["shop_id"], _clean_title(filename), asset_type, theme, "unused", filename, "", "",
                    data, mime, digest, "pending", "",
                ),
            )
            uploaded += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    params = {"uploaded": uploaded, "skipped": skipped}
    if uploaded:
        params["analyze"] = 1
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
        core.db_execute(
            conn,
            "INSERT INTO demand_content_assets (shop_id,title,asset_type,theme,status,source_name,notes,image_url) VALUES (?,?,?,?,?,?,?,?)",
            values,
        )
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
        core.db_execute(
            conn,
            "UPDATE demand_content_assets SET instagram_hook=?,instagram_caption=?,instagram_cta=?,status=? WHERE id=? AND shop_id=?",
            (hook, caption, cta, status, asset_id, user["shop_id"]),
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
