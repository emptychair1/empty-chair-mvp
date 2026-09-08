"""Founder-safe immediate Reel test endpoint.

This module does not publish. It creates a uniquely keyed Reel test row and returns the
same render/upload URLs used by the isolated Reels engine so GitHub Actions can render
an MP4 immediately outside the normal twice-daily schedule.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi import Request

import v2_app as core
import v2_instagram_reels_engine as reels


def _test_slot() -> tuple[str, str]:
    now = datetime.now(timezone.utc).astimezone(reels.EASTERN)
    day = now.date().isoformat()
    slot = "test-" + now.strftime("%H%M%S")
    return slot, day


@core.app.post("/internal/instagram/reels/prepare-test")
def prepare_test_reel(request: Request):
    reels._auth(request)
    slot, day = _test_slot()
    scenario = reels._scenario(day, slot)
    reel_id = "reel_test_" + hashlib.sha256(f"{day}:{slot}".encode()).hexdigest()[:20]
    core.run(
        "INSERT INTO growth_ig_reels(id,local_day,slot,scenario_json,caption,status,created_at) VALUES(?,?,?,?,?,?,?)",
        (reel_id, day, slot, json.dumps(scenario), reels._caption(scenario), "PREPARED", reels._now()),
    )
    return {
        "ok": True,
        "due": True,
        "published": False,
        "test": True,
        "id": reel_id,
        "slot": slot,
        "scene_urls": [f"{reels.BASE_URL}/instagram/reels/render/{reel_id}/{n}" for n in range(5)],
        "upload_url": f"{reels.BASE_URL}/internal/instagram/reels/video/{reel_id}",
        "video_url": f"{reels.BASE_URL}/instagram/reels/video/{reel_id}.mp4",
    }


print("Instagram Reels test-now endpoint loaded // publish disabled", flush=True)
