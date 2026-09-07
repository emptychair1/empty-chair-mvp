"""Expand Hunter's fresh artist inventory from additional public US event rosters.

This module only reads public convention pages and public artist profile pages. It does
not log into Instagram, bypass access controls, infer private contact data, or send any
action. Current/upcoming event participation is inventory evidence only, never pain.
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

HANDLE_RE = re.compile(r"(?<![A-Za-z0-9._])@([A-Za-z0-9._]{2,30})(?![A-Za-z0-9._])")
IG_HOSTS = {"instagram.com", "www.instagram.com"}
RESERVED = {
    "instagram", "tattoo", "tattoos", "tattooartist", "tattooartists",
    "tattooconvention", "facebook", "youtube", "tiktok", "threads",
}

BIZARRE_URL = "https://www.bizarrebazaartatcon.com/2026-lineup"
ANIME_INDEX = "https://animeinkcon.com/exhibitors/artists"
ANIME_PREFIX = "/exhibitors/artists/"


def normalize_handle(value: str) -> str | None:
    handle = (value or "").strip().lstrip("@").lower().strip("/ ")
    if not re.fullmatch(r"[a-z0-9._]{2,30}", handle):
        return None
    if handle in RESERVED or handle.isdigit():
        return None
    return handle


def handle_from_instagram_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.hostname not in IG_HOSTS:
        return None
    first = parsed.path.strip("/").split("/", 1)[0]
    if first in {"p", "reel", "tv", "stories", "explore", "accounts"}:
        return None
    return normalize_handle(first)


def artist_row(handle: str, *, name: str | None, source: str, source_url: str, market: str, event_start: str, event_end: str, now: datetime) -> dict:
    return {
        "username": handle,
        "name": name,
        "profile_url": f"https://www.instagram.com/{handle}/",
        "market": market,
        "activity_source": source,
        "activity_source_url": source_url,
        "event_start": event_start,
        "event_end": event_end,
        "activity_verified_at": now.isoformat(),
        "fresh_activity": True,
        "pain_fit": None,
        "pain_freshness_hours": None,
        "contact": {
            "emails": [],
            "booking_urls": [],
            "website_urls": [],
            "instagram_url": f"https://www.instagram.com/{handle}/",
            "contactability": 40,
            "best_contact_method": "public_instagram_profile",
        },
    }


def extract_bizarre(html: str, now: datetime) -> list[dict]:
    """Read only the tattoo-artist portion of the Bizarre Bazaar public lineup."""
    soup = BeautifulSoup(html, "lxml")
    rows: dict[str, dict] = {}
    stopped = False
    last_name: str | None = None

    for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "a", "div"]):
        text = node.get_text(" ", strip=True)
        upper = text.upper()
        if node.name in {"h2", "h3", "h4"} and any(mark in upper for mark in ("PIERCING", "BOOTH VENDORS", "FOOD VENDORS")):
            stopped = True
        if stopped:
            continue
        if node.name in {"h2", "h3", "h4", "p", "div"} and text and len(text) <= 100 and "IG:" not in upper and not text.startswith("@"):
            last_name = text
        if node.name != "a" or not node.get("href"):
            continue
        handle = handle_from_instagram_url(urljoin(BIZARRE_URL, node.get("href")))
        if not handle:
            continue
        rows[handle] = artist_row(
            handle,
            name=last_name,
            source="Bizarre Bazaar Tattoo Convention 2026",
            source_url=BIZARRE_URL,
            market="Marietta, OH",
            event_start="2026-10-02",
            event_end="2026-10-04",
            now=now,
        )
    return list(rows.values())


def anime_detail_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    base_host = urlparse(ANIME_INDEX).hostname
    links: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = urljoin(ANIME_INDEX, link.get("href", ""))
        parsed = urlparse(href)
        if parsed.hostname == base_host and parsed.path.startswith(ANIME_PREFIX) and parsed.path.rstrip("/") != ANIME_PREFIX.rstrip("/"):
            links.add(href.split("#", 1)[0])
    return sorted(links)


def extract_anime_artist(html: str, page_url: str, now: datetime) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    name_node = soup.find("h1")
    name = name_node.get_text(" ", strip=True) if name_node else None

    # Prefer an explicit Instagram link when the profile provides one.
    for link in soup.find_all("a", href=True):
        handle = handle_from_instagram_url(urljoin(page_url, link.get("href", "")))
        if handle:
            return artist_row(
                handle,
                name=name,
                source="Anime Ink Con 2026",
                source_url=page_url,
                market="Richmond, VA",
                event_start="2026-10-02",
                event_end="2026-10-04",
                now=now,
            )

    # Anime Ink renders many primary handles as text. The first handle near the profile
    # heading is the artist's own handle; later @mentions in About copy are ignored.
    text = soup.get_text(" ", strip=True)
    if name:
        pos = text.find(name)
        if pos >= 0:
            text = text[pos:pos + 700]
    for match in HANDLE_RE.finditer(text):
        handle = normalize_handle(match.group(1))
        if handle:
            return artist_row(
                handle,
                name=name,
                source="Anime Ink Con 2026",
                source_url=page_url,
                market="Richmond, VA",
                event_start="2026-10-02",
                event_end="2026-10-04",
                now=now,
            )
    return None


def merge(existing: dict, incoming: dict) -> dict:
    out = dict(existing)
    sources = list(out.get("activity_sources") or [])
    if not sources and out.get("activity_source"):
        sources.append({
            "name": out.get("activity_source"),
            "url": out.get("activity_source_url"),
            "event_start": out.get("event_start"),
            "event_end": out.get("event_end"),
            "market": out.get("market"),
        })
    candidate = {
        "name": incoming.get("activity_source"),
        "url": incoming.get("activity_source_url"),
        "event_start": incoming.get("event_start"),
        "event_end": incoming.get("event_end"),
        "market": incoming.get("market"),
    }
    if candidate not in sources:
        sources.append(candidate)
    out["activity_sources"] = sources
    if not out.get("name") and incoming.get("name"):
        out["name"] = incoming["name"]
    return out


def run(bucket: dict, *, timeout: float = 20.0, max_anime_pages: int = 500) -> dict:
    now = datetime.now(timezone.utc)
    artists = {str(row.get("username") or "").lower(): row for row in bucket.get("artists", []) if row.get("username")}
    before = len(artists)
    errors: list[dict] = []
    source_counts = {"bizarre_bazaar": 0, "anime_ink": 0}
    headers = {"User-Agent": "EmptyChair-Hunter/1.0 public-roster research; contact=tryemptychair.com"}

    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        try:
            response = client.get(BIZARRE_URL)
            response.raise_for_status()
            rows = extract_bizarre(response.text, now)
            source_counts["bizarre_bazaar"] = len(rows)
            for row in rows:
                key = row["username"]
                artists[key] = merge(artists[key], row) if key in artists else row
        except Exception as exc:
            errors.append({"source": "bizarre_bazaar", "error": type(exc).__name__})

        links: list[str] = []
        try:
            response = client.get(ANIME_INDEX)
            response.raise_for_status()
            links = anime_detail_links(response.text)[:max_anime_pages]
        except Exception as exc:
            errors.append({"source": "anime_ink_index", "error": type(exc).__name__})

    def fetch_anime(url: str) -> dict | None:
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as thread_client:
                response = thread_client.get(url)
                response.raise_for_status()
                return extract_anime_artist(response.text, url, now)
        except Exception:
            return None

    if links:
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {pool.submit(fetch_anime, url): url for url in links}
            for future in as_completed(futures):
                row = future.result()
                if not row:
                    continue
                source_counts["anime_ink"] += 1
                key = row["username"]
                artists[key] = merge(artists[key], row) if key in artists else row

    rows = sorted(artists.values(), key=lambda row: (-int(row.get("contact", {}).get("contactability", 0)), str(row.get("username") or "")))
    bucket["artists"] = rows
    metrics = dict(bucket.get("metrics") or {})
    metrics["unique_artists"] = len(rows)
    metrics["contactable_artists"] = sum(1 for row in rows if int(row.get("contact", {}).get("contactability", 0)) >= 40)
    metrics["expansion_added_to_bucket"] = len(rows) - before
    metrics["bizarre_bazaar_artists"] = source_counts["bizarre_bazaar"]
    metrics["anime_ink_artists"] = source_counts["anime_ink"]
    metrics["anime_ink_profile_pages_discovered"] = len(links)
    bucket["metrics"] = metrics
    bucket.setdefault("errors", []).extend(errors)
    bucket["generated_at"] = now.isoformat()
    return bucket


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default="hunter-fresh-contact-bucket.json")
    parser.add_argument("--out", default="hunter-fresh-contact-bucket.json")
    parser.add_argument("--max-anime-pages", type=int, default=500)
    args = parser.parse_args()

    bucket = json.loads(Path(args.bucket).read_text(encoding="utf-8"))
    result = run(bucket, max_anime_pages=args.max_anime_pages)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m = result.get("metrics", {})
    print(
        "hunter fresh roster expansion // "
        f"total={m.get('unique_artists', 0)} added={m.get('expansion_added_to_bucket', 0)} "
        f"bizarre={m.get('bizarre_bazaar_artists', 0)} anime={m.get('anime_ink_artists', 0)} "
        f"anime_pages={m.get('anime_ink_profile_pages_discovered', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
