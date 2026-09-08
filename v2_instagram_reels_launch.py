"""Launch library and live Instagram Reels publisher.

This lane is isolated from the proven square-image Instagram publisher. It reuses the
existing Reels storage table and Meta credentials but creates REELS media containers,
not image containers.
"""
from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

import v2_app as core
import v2_instagram_growth as growth
import v2_instagram_publisher as publisher
import v2_instagram_reels_engine as reels

LAUNCH_DAY = "2026-09-08"
PRODUCT_SCENES = 5

RECOVERY_TITLES = [
    "Same-day $450 recovery",
    "Tomorrow $600 recovery",
    "Evening $350 recovery",
    "Saturday $700 recovery",
    "90-minute $300 recovery",
    "$900 full-day recovery",
]

PRODUCT_LIBRARY = [
    {
        "key": "artist-setup",
        "family": "SETUP",
        "title": "Set up an artist",
        "hook": "ADD THE ARTIST. EMPTY CHAIR TAKES IT FROM THERE.",
        "assets": ["setup.png", "artists.png", "calendar.png", "settings.png", "openings-recovery.png"],
        "lines": ["START THE STUDIO", "ADD THE ARTIST", "CONNECT THE CALENDAR", "SET RECOVERY + PAYMENTS", "READY FOR THE NEXT CANCELLATION"],
    },
    {
        "key": "calendar-setup",
        "family": "SETUP",
        "title": "Connect the calendar",
        "hook": "THE CALENDAR IS THE TRIGGER.",
        "assets": ["calendar.png", "settings.png", "calendar.png", "openings-recovery.png", "operations.png"],
        "lines": ["YOUR REAL CALENDAR", "CONNECT IT ONCE", "EMPTY CHAIR WATCHES OPENINGS", "A CANCELLATION STARTS RECOVERY", "THE SLOT GETS FILLED BACK IN"],
    },
    {
        "key": "payment-setup",
        "family": "SETUP",
        "title": "Set the deposit",
        "hook": "THE CHAIR ISN'T FILLED UNTIL THE DEPOSIT LANDS.",
        "assets": ["settings.png", "artists.png", "openings-recovery.png", "revenue.png", "calendar.png"],
        "lines": ["OPEN PAYMENT SETTINGS", "SET THE ARTIST'S DEPOSIT", "THE CLIENT TAKES THE CHAIR", "DEPOSIT CONFIRMS THE RECOVERY", "BOOKING RETURNS TO THE CALENDAR"],
    },
    {
        "key": "bench",
        "family": "MATCHING",
        "title": "Build the bench",
        "hook": "A LAST-MINUTE OPENING IS USELESS WITHOUT PEOPLE READY TO TAKE IT.",
        "assets": ["customers.png", "customer-intelligence.png", "artists.png", "openings-recovery.png", "operations.png"],
        "lines": ["YOUR CUSTOMER BENCH", "PREFERENCES + HISTORY", "MATCHED TO THE RIGHT ARTIST", "BEST MATCH GETS THE OFFER", "RECOVERY MOVES FORWARD"],
    },
    {
        "key": "matching",
        "family": "MATCHING",
        "title": "Why Empty Chair does not blast everyone",
        "hook": "DON'T BLAST EVERY CLIENT. FIND THE RIGHT ONE.",
        "assets": ["customers.png", "customer-intelligence.png", "openings-recovery.png", "operations.png", "calendar.png"],
        "lines": ["THE BENCH IS ALREADY THERE", "FIT MATTERS", "ONE OPENING. BEST MATCH FIRST.", "NEXT MATCH ONLY IF NEEDED", "THE CHAIR GETS FILLED"],
    },
    {
        "key": "weekly-report",
        "family": "PROOF",
        "title": "Weekly recovery report",
        "hook": "DEMO SHOP // SAMPLE WEEKLY RECOVERY REPORT",
        "assets": ["revenue.png", "operations.png", "openings-recovery.png", "calendar.png", "revenue.png"],
        "lines": ["DEMO SHOP // SAMPLE REPORT", "4 CANCELLATIONS THIS WEEK", "3 RECOVERED", "$1,450 SAMPLE REVENUE SAVED", "THIS IS A DEMO, NOT A CUSTOMER CLAIM"],
    },
    {
        "key": "monthly-report",
        "family": "PROOF",
        "title": "Monthly recovery report",
        "hook": "DEMO SHOP // SAMPLE MONTHLY RECOVERY REPORT",
        "assets": ["revenue.png", "operations.png", "calendar.png", "openings-recovery.png", "revenue.png"],
        "lines": ["DEMO SHOP // SAMPLE REPORT", "18 CANCELLATIONS THIS MONTH", "14 SAMPLE RECOVERIES", "$6,800 SAMPLE REVENUE SAVED", "REAL ACCOUNTS USE THEIR OWN DATA"],
    },
    {
        "key": "daily-report",
        "family": "PROOF",
        "title": "Today in Empty Chair",
        "hook": "DEMO SHOP // TODAY: TWO CHAIRS AT RISK.",
        "assets": ["calendar.png", "openings-recovery.png", "operations.png", "calendar.png", "revenue.png"],
        "lines": ["DEMO SHOP // TODAY", "2 CHAIRS AT RISK", "RECOVERY IS WORKING", "1 SLOT BACK ON THE CALENDAR", "SAMPLE STATUS // NOT A CUSTOMER CLAIM"],
    },
    {
        "key": "what-happens",
        "family": "EDUCATION",
        "title": "What happens when someone cancels?",
        "hook": "WHAT ACTUALLY HAPPENS WHEN A CLIENT CANCELS?",
        "assets": ["calendar.png", "customers.png", "openings-recovery.png", "revenue.png", "calendar.png"],
        "lines": ["1 // THE CALENDAR OPENS", "2 // EMPTY CHAIR FINDS THE BENCH", "3 // THE RIGHT CLIENT GETS THE OFFER", "4 // THE DEPOSIT LANDS", "5 // THE CALENDAR IS FILLED AGAIN"],
    },
    {
        "key": "first-recovery",
        "family": "PRODUCT",
        "title": "From setup to first recovery",
        "hook": "FROM NEW ACCOUNT TO FIRST RECOVERED CHAIR.",
        "assets": ["setup.png", "artists.png", "calendar.png", "openings-recovery.png", "revenue.png"],
        "lines": ["CREATE THE STUDIO", "ADD THE ARTIST", "CONNECT THE CALENDAR", "A CANCELLATION STARTS RECOVERY", "THE DEPOSIT CONFIRMS THE FILL"],
    },
]


def _caption(item: dict) -> str:
    return (
        f"{item['hook']}\n\n"
        "Empty Chair is built for one job: recover canceled tattoo appointments.\n\n"
        "7 DAYS FREE // LINK IN BIO\n\n"
        "#tattooartist #tattooshop #tattoocancellation #booksopen #emptychair"
    )


def _launch_id(slot: str) -> str:
    return "reel_launch_" + hashlib.sha256(f"{LAUNCH_DAY}:{slot}".encode()).hexdigest()[:20]


def _ensure_row(slot: str, scenario: dict, caption: str) -> dict:
    existing = core.one("SELECT * FROM growth_ig_reels WHERE local_day=? AND slot=?", (LAUNCH_DAY, slot))
    if existing:
        return existing
    reel_id = _launch_id(slot)
    core.run(
        "INSERT INTO growth_ig_reels(id,local_day,slot,scenario_json,caption,status,created_at) VALUES(?,?,?,?,?,?,?)",
        (reel_id, LAUNCH_DAY, slot, json.dumps(scenario), caption, "PREPARED", reels._now()),
    )
    return core.one("SELECT * FROM growth_ig_reels WHERE id=?", (reel_id,))


def _product_html(item: dict, scene: int) -> str:
    asset = html.escape(item["assets"][scene])
    line = html.escape(item["lines"][scene])
    family = html.escape(item["family"])
    title = html.escape(item["title"])
    hook = html.escape(item["hook"])
    asset_url = html.escape(f"{reels.BASE_URL}/static/{asset}", quote=True)
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<style>
*{{box-sizing:border-box}}html,body{{margin:0;width:1080px;height:1920px;overflow:hidden;background:#0B0905}}body{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}.screen{{width:1080px;height:1920px;position:relative;background:#0B0905;color:#FFD36A;overflow:hidden}}.shot{{position:absolute;left:70px;right:70px;top:325px;height:1070px;border:2px solid #5f4100;background:#171108;overflow:hidden;box-shadow:0 0 60px rgba(255,176,0,.11)}}.shot img{{width:100%;height:100%;object-fit:contain;background:#0B0905}}.eyebrow{{position:absolute;top:95px;left:70px;right:70px;color:#805800;font-size:24px;letter-spacing:.18em}}h1{{position:absolute;top:145px;left:70px;right:70px;margin:0;font-size:54px;line-height:1.08;font-weight:500}}.line{{position:absolute;left:70px;right:70px;bottom:285px;border-top:2px solid #5f4100;padding-top:38px;font-size:48px;line-height:1.13;color:#FFD36A}}.hook{{position:absolute;left:70px;right:70px;bottom:130px;color:#FFB000;font-size:24px;line-height:1.35}}.brand{{position:absolute;right:70px;top:90px;color:#FFB000;font-size:20px}}
</style></head><body><main class='screen'><div class='eyebrow'>{family} // EMPTY CHAIR</div><div class='brand'>2.0</div><h1>{title}</h1><div class='shot'><img src='{asset_url}' alt='Real Empty Chair product screen'></div><div class='line'>{line}</div><div class='hook'>{hook}</div></main></body></html>"""


def _items() -> list[dict]:
    out: list[dict] = []
    for index, scenario in enumerate(reels.SCENARIOS):
        s = dict(scenario)
        s["launch_family"] = "RECOVERY"
        slot = f"launch-{index+1:02d}-recovery-{s['kind']}"
        row = _ensure_row(slot, s, reels._caption(s))
        out.append({
            "id": row["id"], "slot": slot, "family": "RECOVERY", "title": RECOVERY_TITLES[index],
            "scene_urls": [f"{reels.BASE_URL}/instagram/reels/render/{row['id']}/{n}" for n in range(reels.SCENE_COUNT)],
            "upload_url": f"{reels.BASE_URL}/internal/instagram/reels/video/{row['id']}",
            "video_url": f"{reels.BASE_URL}/instagram/reels/video/{row['id']}.mp4",
            "publish_url": f"{reels.BASE_URL}/internal/instagram/reels/launch/publish/{row['id']}",
            "status": row.get("status"), "media_id": row.get("media_id"),
        })
    for offset, item in enumerate(PRODUCT_LIBRARY, start=7):
        slot = f"launch-{offset:02d}-{item['key']}"
        scenario = {**item, "kind": "launch_product", "launch_family": item["family"]}
        row = _ensure_row(slot, scenario, _caption(item))
        out.append({
            "id": row["id"], "slot": slot, "family": item["family"], "title": item["title"],
            "scene_urls": [f"{reels.BASE_URL}/instagram/reels/launch/render/{row['id']}/{n}" for n in range(PRODUCT_SCENES)],
            "upload_url": f"{reels.BASE_URL}/internal/instagram/reels/video/{row['id']}",
            "video_url": f"{reels.BASE_URL}/instagram/reels/video/{row['id']}.mp4",
            "publish_url": f"{reels.BASE_URL}/internal/instagram/reels/launch/publish/{row['id']}",
            "status": row.get("status"), "media_id": row.get("media_id"),
        })
    return out


@core.app.post("/internal/instagram/reels/launch/prepare")
def prepare_launch_library(request: Request):
    reels._auth(request)
    items = _items()
    return {"ok": True, "count": len(items), "items": items}


@core.app.get("/instagram/reels/launch/render/{reel_id}/{scene}", response_class=HTMLResponse)
def render_launch_scene(reel_id: str, scene: int):
    row = core.one("SELECT scenario_json FROM growth_ig_reels WHERE id=?", (reel_id,))
    if not row or scene < 0 or scene >= PRODUCT_SCENES:
        raise HTTPException(404, "Not found")
    item = json.loads(str(row["scenario_json"]))
    if item.get("kind") != "launch_product":
        raise HTTPException(404, "Not found")
    return HTMLResponse(_product_html(item, scene))


@core.app.post("/internal/instagram/reels/launch/publish/{reel_id}")
def publish_launch_reel(reel_id: str, request: Request):
    reels._auth(request)
    row = core.one("SELECT * FROM growth_ig_reels WHERE id=?", (reel_id,))
    if not row:
        raise HTTPException(404, "Not found")
    if str(row.get("status") or "") == "PUBLISHED" and row.get("media_id"):
        return {"ok": True, "published": True, "already": True, "media_id": row["media_id"]}
    if not row.get("video_bytes") or str(row.get("status") or "") != "RENDERED":
        raise HTTPException(409, "Reel must be rendered before publishing")
    if not (growth.META_TOKEN and growth.IG_USER_ID):
        raise HTTPException(503, "Instagram publishing credentials are not configured")

    video_url = f"{reels.BASE_URL}/instagram/reels/video/{reel_id}.mp4"
    try:
        created = publisher._post(f"{growth.IG_USER_ID}/media", {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": str(row.get("caption") or ""),
            "share_to_feed": "true",
        })
        creation_id = str(created.get("id") or "")
        if not creation_id:
            raise RuntimeError(f"Instagram Reel container failed: {created}")
        publisher._wait_ready(creation_id, attempts=36, delay=5)
        published = publisher._post(f"{growth.IG_USER_ID}/media_publish", {"creation_id": creation_id})
        media_id = str(published.get("id") or "")
        if not media_id:
            raise RuntimeError(f"Instagram Reel publish failed: {published}")
        now = datetime.now(timezone.utc).isoformat()
        core.run("UPDATE growth_ig_reels SET status='PUBLISHED',media_id=?,published_at=? WHERE id=?", (media_id, now, reel_id))
        core.event("growth.instagram_reel_published", None, {"reel_id": reel_id, "media_id": media_id, "slot": row.get("slot")})
        print(f"IG Reel published // {reel_id} // {media_id}", flush=True)
        return {"ok": True, "published": True, "media_id": media_id}
    except Exception as exc:
        core.event("growth.instagram_reel_publish_failed", None, {"reel_id": reel_id, "error": str(exc)[:1400]})
        print(f"IG Reel publish failed // {reel_id} // {exc}", flush=True)
        raise HTTPException(502, str(exc)[:500])


print("Instagram Reels launch library loaded // 16 concepts // live publisher enabled", flush=True)
