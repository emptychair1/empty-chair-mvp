"""Scheduling + Instagram publishing for Demand Content."""
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import app as core
import demand_content
import content_attribution

POST_HOUR = int(os.getenv("EMPTY_CHAIR_CONTENT_POST_HOUR", "12"))
POST_MINUTE = int(os.getenv("EMPTY_CHAIR_CONTENT_POST_MINUTE", "30"))
PUBLISH_INTERVAL = max(30, int(os.getenv("EMPTY_CHAIR_CONTENT_PUBLISH_INTERVAL_SECONDS", "60")))
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "").strip()
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v23.0").strip() or "v23.0"
BASE_URL = os.getenv("EMPTY_CHAIR_BASE_URL", "https://app.tryemptychair.com").rstrip("/")
_worker_started = False
_worker_lock = threading.Lock()


def _ensure_schema(conn):
    demand_content._ensure_tables(conn)
    for column in ("scheduled_at", "published_at", "instagram_media_id", "instagram_permalink", "publish_error", "publish_token"):
        demand_content._ensure_column(conn, column)
    demand_content._ensure_column(conn, "publish_attempts", "INTEGER NOT NULL DEFAULT 0")
    content_attribution.ensure_schema(conn)
    conn.commit()


def _shop_timezone(conn, shop_id):
    row = core.db_fetchone(conn, "SELECT timezone FROM shops WHERE id=?", (shop_id,))
    name = str((row["timezone"] if row else None) or "America/New_York")
    try: return ZoneInfo(name), name
    except Exception: return ZoneInfo("America/New_York"), "America/New_York"


def _parse_iso(value):
    if not value: return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception: return None


def _next_slot(conn, shop_id):
    tz, _ = _shop_timezone(conn, shop_id); now_utc = datetime.now(timezone.utc); now_local = now_utc.astimezone(tz)
    latest = core.db_fetchone(conn, "SELECT scheduled_at FROM demand_content_assets WHERE shop_id=? AND status='queued' AND scheduled_at IS NOT NULL ORDER BY scheduled_at DESC LIMIT 1", (shop_id,))
    latest_dt = _parse_iso(latest["scheduled_at"] if latest else None)
    if latest_dt and latest_dt > now_utc: day = latest_dt.astimezone(tz).date() + timedelta(days=1)
    else:
        day = now_local.date(); today_slot = datetime(day.year, day.month, day.day, POST_HOUR, POST_MINUTE, tzinfo=tz)
        if today_slot <= now_local + timedelta(minutes=5): day += timedelta(days=1)
    return datetime(day.year, day.month, day.day, POST_HOUR, POST_MINUTE, tzinfo=tz).astimezone(timezone.utc)


def _queue_asset(conn, shop_id, asset_id, hook=None, caption=None, cta=None):
    row = core.db_fetchone(conn, "SELECT id,title,instagram_hook,scheduled_at,publish_token FROM demand_content_assets WHERE id=? AND shop_id=?", (asset_id, shop_id))
    if not row: return None
    scheduled = _parse_iso(row["scheduled_at"])
    if not scheduled or scheduled <= datetime.now(timezone.utc): scheduled = _next_slot(conn, shop_id)
    token = str(row["publish_token"] or "") or secrets.token_urlsafe(24)
    campaign_id = content_attribution.ensure_asset_campaign(conn, shop_id, asset_id, row["title"], hook or row["instagram_hook"])
    link = content_attribution.tracked_url(BASE_URL, shop_id, campaign_id)
    cta_text = (cta or "Want something in this direction? Tell me what you're thinking.").strip()
    if link not in cta_text: cta_text = f"{cta_text} {link}"
    fields = ["status='queued'", "scheduled_at=?", "publish_token=?", "publish_error=''", "publish_attempts=0", "instagram_cta=?"]
    params = [scheduled.isoformat(), token, cta_text]
    if hook is not None: fields.append("instagram_hook=?"); params.append(hook)
    if caption is not None: fields.append("instagram_caption=?"); params.append(caption)
    params.extend([asset_id, shop_id]); core.db_execute(conn, f"UPDATE demand_content_assets SET {','.join(fields)} WHERE id=? AND shop_id=?", tuple(params))
    return scheduled


def _caption_for(row):
    caption = str(row["instagram_caption"] or "").strip(); cta = str(row["instagram_cta"] or "").strip()
    return caption + (("\n\n" + cta) if cta else "")


def _graph_post(path, data):
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(f"https://graph.facebook.com/{META_GRAPH_VERSION}/{path.lstrip('/')}", data=encoded, headers={"Content-Type":"application/x-www-form-urlencoded"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as response: return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail=exc.read().decode("utf-8",errors="replace"); raise RuntimeError(f"Instagram HTTP {exc.code}: {detail[:700]}") from exc


def _publish_to_instagram(row):
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_BUSINESS_ACCOUNT_ID: raise RuntimeError("Instagram publishing is not configured.")
    token=str(row["publish_token"] or "")
    if not token: raise RuntimeError("Public image token is missing.")
    created=_graph_post(f"{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media",{"image_url":f"{BASE_URL}/content-media/{row['id']}/{urllib.parse.quote(token)}","caption":_caption_for(row),"access_token":INSTAGRAM_ACCESS_TOKEN})
    creation_id=str(created.get("id") or "")
    if not creation_id: raise RuntimeError(f"Instagram did not return a creation id: {created}")
    published=_graph_post(f"{INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish",{"creation_id":creation_id,"access_token":INSTAGRAM_ACCESS_TOKEN})
    media_id=str(published.get("id") or "")
    if not media_id: raise RuntimeError(f"Instagram did not return a media id: {published}")
    return media_id


def _publish_due_once():
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_BUSINESS_ACCOUNT_ID: return 0
    conn=core.connect()
    try:
        _ensure_schema(conn); now=datetime.now(timezone.utc).isoformat()
        rows=core.db_fetchall(conn,"SELECT id,shop_id,image_data,image_mime,instagram_caption,instagram_cta,publish_token FROM demand_content_assets WHERE status='queued' AND scheduled_at IS NOT NULL AND scheduled_at<=? ORDER BY scheduled_at ASC LIMIT 5",(now,)); count=0
        for row in rows:
            claimed=core.db_execute(conn,"UPDATE demand_content_assets SET status='publishing',publish_attempts=publish_attempts+1 WHERE id=? AND status='queued'",(row["id"],))
            if getattr(claimed,"rowcount",0)!=1: conn.rollback(); continue
            conn.commit()
            try:
                media_id=_publish_to_instagram(row); core.db_execute(conn,"UPDATE demand_content_assets SET status='published',published_at=?,instagram_media_id=?,publish_error='' WHERE id=?",(datetime.now(timezone.utc).isoformat(),media_id,row["id"])); conn.commit(); count+=1
            except Exception as exc:
                core.db_execute(conn,"UPDATE demand_content_assets SET status='queued',publish_error=? WHERE id=?",(str(exc)[:900],row["id"])); conn.commit()
        return count
    finally: conn.close()


def _worker_loop():
    while True:
        try: _publish_due_once()
        except Exception as exc: print(f"Content publisher error: {type(exc).__name__}: {exc}",flush=True)
        time.sleep(PUBLISH_INTERVAL)

@core.app.on_event("startup")
def start_content_publisher():
    global _worker_started
    if os.getenv("EMPTY_CHAIR_WORKER_ENABLED","false").lower()!="true": return
    with _worker_lock:
        if _worker_started: return
        _worker_started=True; threading.Thread(target=_worker_loop,name="content-publisher",daemon=True).start()

@core.app.post("/demand-acquisition/content/{asset_id}/queue")
async def queue_content_asset(asset_id:int,request:Request):
    user,redirect=core.login_required_redirect(request)
    if redirect:return redirect
    form=await request.form(); conn=core.connect()
    try:
        _ensure_schema(conn); scheduled=_queue_asset(conn,user["shop_id"],asset_id,str(form.get("instagram_hook") or "").strip(),str(form.get("instagram_caption") or "").strip(),str(form.get("instagram_cta") or "").strip())
        if not scheduled:return RedirectResponse("/demand-acquisition/content",status_code=303)
        conn.commit()
    finally:conn.close()
    return RedirectResponse("/demand-acquisition/content/calendar",status_code=303)

@core.app.post("/demand-acquisition/content/queue-all")
def queue_all_content(request:Request):
    user,redirect=core.login_required_redirect(request)
    if redirect:return redirect
    conn=core.connect()
    try:
        _ensure_schema(conn); rows=core.db_fetchall(conn,"SELECT id FROM demand_content_assets WHERE shop_id=? AND analysis_status='complete' AND status='unused' AND instagram_hook IS NOT NULL AND instagram_hook<>'' AND image_data IS NOT NULL ORDER BY created_at ASC,id ASC",(user["shop_id"],))
        for row in rows:_queue_asset(conn,user["shop_id"],row["id"])
        conn.commit()
    finally:conn.close()
    return RedirectResponse("/demand-acquisition/content/calendar",status_code=303)

@core.app.post("/demand-acquisition/content/{asset_id}/schedule")
async def reschedule_content(asset_id:int,request:Request):
    user,redirect=core.login_required_redirect(request)
    if redirect:return redirect
    form=await request.form(); value=str(form.get("scheduled_at") or "").strip(); conn=core.connect()
    try:
        _ensure_schema(conn); tz,_=_shop_timezone(conn,user["shop_id"])
        try:
            local=datetime.fromisoformat(value)
            if local.tzinfo is None:local=local.replace(tzinfo=tz)
            core.db_execute(conn,"UPDATE demand_content_assets SET scheduled_at=?,status='queued',publish_error='' WHERE id=? AND shop_id=?",(local.astimezone(timezone.utc).isoformat(),asset_id,user["shop_id"]));conn.commit()
        except Exception:pass
    finally:conn.close()
    return RedirectResponse("/demand-acquisition/content/calendar",status_code=303)

@core.app.get("/demand-acquisition/content/calendar",response_class=HTMLResponse)
def content_calendar(request:Request):
    user,redirect=core.login_required_redirect(request)
    if redirect:return redirect
    conn=core.connect()
    try:
        _ensure_schema(conn);tz,tz_name=_shop_timezone(conn,user["shop_id"]);metrics=content_attribution.kpis(conn,user["shop_id"])
        rows=[dict(r) for r in core.db_fetchall(conn,"SELECT id,title,theme,status,scheduled_at,published_at,publish_error,publish_attempts,instagram_caption,instagram_cta,instagram_media_id,manual_meta_scheduled,manual_meta_scheduled_at,acquisition_campaign_id FROM demand_content_assets WHERE shop_id=? AND status IN ('queued','publishing','published') ORDER BY CASE WHEN scheduled_at IS NULL THEN 1 ELSE 0 END,scheduled_at ASC,id ASC",(user["shop_id"],))]
        for row in rows:
            campaign_id=content_attribution.ensure_asset_campaign(conn,user["shop_id"],row["id"],row["title"],""); row["tracked_url"]=content_attribution.tracked_url(BASE_URL,user["shop_id"],campaign_id)
            if row["tracked_url"] not in str(row.get("instagram_cta") or ""):
                row["instagram_cta"]=(str(row.get("instagram_cta") or "Want something in this direction? Tell me what you're thinking.").strip()+" "+row["tracked_url"]);core.db_execute(conn,"UPDATE demand_content_assets SET instagram_cta=? WHERE id=? AND shop_id=?",(row["instagram_cta"],row["id"],user["shop_id"]))
        conn.commit()
    finally:conn.close()
    for row in rows:
        row["image_url"]=f"/demand-acquisition/content/{row['id']}/image";dt=_parse_iso(row.get("scheduled_at"))
        if dt:
            local=dt.astimezone(tz);row["scheduled_display"]=local.strftime("%a %b %-d · %-I:%M %p");row["scheduled_input"]=local.strftime("%Y-%m-%dT%H:%M")
        else:row["scheduled_display"]="Unscheduled";row["scheduled_input"]=""
    return core.templates.TemplateResponse(request=request,name="content_calendar.html",context={"user":user,"items":rows,"metrics":metrics,"timezone_name":tz_name,"instagram_configured":bool(INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID),"post_time":f"{POST_HOUR:02d}:{POST_MINUTE:02d}"},headers={"Cache-Control":"no-store"})

@core.app.get("/content-media/{asset_id}/{token}")
def public_content_media(asset_id:int,token:str):
    conn=core.connect()
    try:_ensure_schema(conn);row=core.db_fetchone(conn,"SELECT image_data,image_mime,publish_token,status FROM demand_content_assets WHERE id=? AND publish_token=?",(asset_id,token))
    finally:conn.close()
    if not row or not row["image_data"] or row["status"] not in {"queued","publishing","published"}:return Response(status_code=404)
    return Response(content=bytes(row["image_data"]),media_type=row["image_mime"] or "image/jpeg",headers={"Cache-Control":"public, max-age=3600"})
