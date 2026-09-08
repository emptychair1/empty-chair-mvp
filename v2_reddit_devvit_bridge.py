"""Devvit -> Empty Chair Reddit opportunity bridge.

Reddit's current developer platform owns Reddit API auth. A small Devvit worker
searches Reddit on schedule and POSTs normalized public thread metadata here.
The Founder Reddit Copilot then reads this cache first and keeps anonymous Reddit
search only as a fallback.
"""
from __future__ import annotations

import os
import time
from typing import Any

from fastapi import HTTPException, Request

import v2_app as core
import v2_founder_reddit as reddit_ui

INGEST_TOKEN = os.getenv("HUNTER_OPERATOR_INGEST_TOKEN", "").strip()


def _ensure_table() -> None:
    core.run(
        """
        CREATE TABLE IF NOT EXISTS founder_reddit_opportunities (
            reddit_id TEXT PRIMARY KEY,
            subreddit TEXT NOT NULL,
            title TEXT NOT NULL,
            selftext TEXT NOT NULL DEFAULT '',
            permalink TEXT NOT NULL,
            created_utc REAL NOT NULL DEFAULT 0,
            num_comments INTEGER NOT NULL DEFAULT 0,
            reddit_score INTEGER NOT NULL DEFAULT 0,
            fetched_at REAL NOT NULL
        )
        """
    )


try:
    _ensure_table()
except Exception as exc:
    print(f"Founder Reddit Devvit table init deferred // {exc}", flush=True)


def _auth(request: Request) -> None:
    if not INGEST_TOKEN:
        raise HTTPException(503, "Reddit ingest token is not configured")
    supplied = (request.headers.get("x-empty-chair-token") or "").strip()
    if not supplied or supplied != INGEST_TOKEN:
        raise HTTPException(401, "Unauthorized")


@core.app.post("/internal/reddit/devvit-ingest")
async def reddit_devvit_ingest(request: Request):
    _auth(request)
    payload: Any = await request.json()
    items = payload.get("posts", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        raise HTTPException(400, "posts must be a list")

    _ensure_table()
    accepted = 0
    now = time.time()
    for raw in items[:100]:
        if not isinstance(raw, dict):
            continue
        reddit_id = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip()
        subreddit = str(raw.get("subreddit") or "").strip()
        permalink = str(raw.get("permalink") or "").strip()
        if not reddit_id or not title or not subreddit or not permalink:
            continue
        selftext = str(raw.get("selftext") or "")[:12000]
        created_utc = float(raw.get("createdUtc") or raw.get("created_utc") or 0)
        num_comments = int(raw.get("numComments") or raw.get("num_comments") or 0)
        reddit_score = int(raw.get("score") or 0)
        core.run(
            """
            INSERT INTO founder_reddit_opportunities
                (reddit_id, subreddit, title, selftext, permalink, created_utc, num_comments, reddit_score, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(reddit_id) DO UPDATE SET
                subreddit=excluded.subreddit,
                title=excluded.title,
                selftext=excluded.selftext,
                permalink=excluded.permalink,
                created_utc=excluded.created_utc,
                num_comments=excluded.num_comments,
                reddit_score=excluded.reddit_score,
                fetched_at=excluded.fetched_at
            """,
            (reddit_id, subreddit, title, selftext, permalink, created_utc, num_comments, reddit_score, now),
        )
        accepted += 1

    # Keep the cache lean. We only need recent conversation opportunities.
    try:
        core.run("DELETE FROM founder_reddit_opportunities WHERE fetched_at < ?", (now - 60 * 60 * 24 * 45,))
    except Exception:
        pass
    return {"ok": True, "accepted": accepted}


def _cached_posts() -> list[dict]:
    try:
        _ensure_table()
        rows = core.all(
            """
            SELECT reddit_id, subreddit, title, selftext, permalink,
                   created_utc, num_comments, reddit_score, fetched_at
            FROM founder_reddit_opportunities
            WHERE fetched_at >= ?
            ORDER BY created_utc DESC
            LIMIT 120
            """,
            (time.time() - 60 * 60 * 24 * 30,),
        )
    except Exception as exc:
        print(f"Founder Reddit cache read failed // {exc}", flush=True)
        return []

    out: list[dict] = []
    for row in rows or []:
        # core rows can be sqlite Row, dict-like, or tuple depending on backend.
        try:
            get = row.get  # type: ignore[attr-defined]
            item = {
                "id": str(get("reddit_id") or ""),
                "subreddit": str(get("subreddit") or ""),
                "subreddit_name_prefixed": "r/" + str(get("subreddit") or ""),
                "title": str(get("title") or ""),
                "selftext": str(get("selftext") or ""),
                "permalink": str(get("permalink") or ""),
                "created_utc": float(get("created_utc") or 0),
                "num_comments": int(get("num_comments") or 0),
                "score": int(get("reddit_score") or 0),
            }
        except Exception:
            try:
                item = {
                    "id": str(row[0]), "subreddit": str(row[1]),
                    "subreddit_name_prefixed": "r/" + str(row[1]),
                    "title": str(row[2]), "selftext": str(row[3] or ""),
                    "permalink": str(row[4]), "created_utc": float(row[5] or 0),
                    "num_comments": int(row[6] or 0), "score": int(row[7] or 0),
                }
            except Exception:
                continue
        score, label, angle = reddit_ui._score(item)
        item["ec_score"] = score
        item["ec_label"] = label
        item["ec_angle"] = angle
        reply, mode = reddit_ui._suggest_reply(item)
        item["ec_reply"] = reply
        item["ec_reply_mode"] = mode
        out.append(item)
    return out


_original_opportunities = reddit_ui._opportunities


def _devvit_first_opportunities():
    cached = _cached_posts()
    if cached:
        ranked = sorted(
            cached,
            key=lambda p: (int(p.get("ec_score") or 0), float(p.get("created_utc") or 0)),
            reverse=True,
        )
        return [p for p in ranked if int(p.get("ec_score") or 0) >= 25][:20], True
    return _original_opportunities()


reddit_ui._opportunities = _devvit_first_opportunities

print("Founder Reddit Devvit bridge loaded // authenticated ingest + cached radar", flush=True)
