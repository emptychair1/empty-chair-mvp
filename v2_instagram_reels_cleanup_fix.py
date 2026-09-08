"""Fast safety cleanup for obsolete Reel renders.

Quarantines obsolete launch/test videos first so they cannot be downloaded, then removes
rows in small batches. Kept isolated from the normal Reels autopilot.
"""
from __future__ import annotations

from fastapi import Request

import v2_app as core
import v2_instagram_reels_engine as reels


@core.app.post("/internal/instagram/reels/cleanup-obsolete-fast")
def cleanup_obsolete_reels_fast(request: Request):
    reels._auth(request)

    # First make every obsolete Reel immediately unusable/download-safe.
    core.run(
        "UPDATE growth_ig_reels SET video_bytes=NULL,status='OBSOLETE' "
        "WHERE slot LIKE 'test-%' OR slot LIKE 'launch-%'"
    )

    rows = core.all_rows(
        "SELECT id FROM growth_ig_reels "
        "WHERE slot LIKE 'test-%' OR slot LIKE 'launch-%' LIMIT 100"
    )
    deleted = 0
    for row in rows:
        core.run("DELETE FROM growth_ig_reels WHERE id=?", (row["id"],))
        deleted += 1

    remaining_row = core.one(
        "SELECT COUNT(*) AS n FROM growth_ig_reels "
        "WHERE slot LIKE 'test-%' OR slot LIKE 'launch-%'"
    )
    remaining = int((remaining_row or {}).get("n") or 0)
    print(
        f"IG Reels fast cleanup // deleted={deleted} remaining={remaining}",
        flush=True,
    )
    return {"ok": True, "deleted": deleted, "remaining": remaining}


print("Instagram Reels fast cleanup loaded // obsolete MP4 quarantine + batch delete", flush=True)
