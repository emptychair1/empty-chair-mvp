"""Build Hunter's fresh, contactable tattoo-artist bucket from public web rosters.

This source is intentionally independent of Meta inventory. It only uses public pages
that explicitly publish tattoo-artist participation/contact information. Freshness is
based on a current or upcoming event/roster window; that proves recent artist activity,
not Empty Chair pain. Pain remains a separate <=72h signal when available.

No private data is inferred, no email addresses are guessed, and no outreach is sent.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![A-Z0-9._%+-])", re.I)
HANDLE_RE = re.compile(r"(?<![A-Za-z0-9._])@([A-Za-z0-9._]{2,30})(?![A-Za-z0-9._])")
IG_HOSTS = {"instagram.com", "www.instagram.com"}
RESERVED_HANDLES = {
    "instagram", "tattoo", "tattoos", "tattooartist", "tattooartists", "tattooconvention",
    "facebook", "youtube", "tiktok", "twitter", "threads", "gmail", "yahoo", "outlook",
}
CONTACT_WORDS = ("book", "booking", "appointment", "contact", "inquiry", "inquiries", "schedule")


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    event_start: date
    event_end: date
    market: str


# Current/future US artist rosters. Event dates are explicit stale-lead guards.
DEFAULT_SOURCES = (
    Source("Southeast Tattoo Expo", "https://setattoo.com/attending-artists%2Fvendors", date(2026, 9, 11), date(2026, 9, 13), "Southeast US"),
    Source("Golden State Tattoo Expo", "https://goldenstatetattooexpo.com/artists", date(2026, 9, 18), date(2026, 9, 20), "Pasadena, CA"),
    Source("Three Rivers Tattoo Convention", "https://trtattcon.com/artists/", date(2026, 9, 25), date(2026, 9, 27), "Kennewick, WA"),
    Source("Summit Invitational", "https://www.summitinvitational.com/", date(2026, 10, 9), date(2026, 10, 11), "Colorado"),
)


def normalize_handle(value: str) -> str | None:
    clean = (value or "").strip().lstrip("@").lower().strip("/ ")
    if not re.fullmatch(r"[a-z0-9._]{2,30}", clean):
        return None
    if clean in RESERVED_HANDLES or clean.isdigit():
        return None
    return clean


def instagram_handle_from_url(href: str) -> str | None:
    try:
        parsed = urlparse(href)
    except ValueError:
        return None
    if parsed.hostname not in IG_HOSTS:
        return None
    first = parsed.path.strip("/").split("/", 1)[0]
    if first in {"p", "reel", "tv", "explore", "accounts", "stories"}:
        return None
    return normalize_handle(first)


def source_is_fresh(source: Source, today: date, *, grace_days: int = 7, horizon_days: int = 120) -> bool:
    return source.event_end >= today - timedelta(days=grace_days) and source.event_start <= today + timedelta(days=horizon_days)


def nearest_artist_block(node) -> object:
    current = node
    fallback = node.parent
    for _ in range(6):
        current = getattr(current, "parent", None)
        if current is None:
            break
        if getattr(current, "name", None) in {"article", "li", "section", "div", "tr"}:
            text = current.get_text(" ", strip=True)
            if 10 <= len(text) <= 2500:
                fallback = current
                if any(token in text.lower() for token in ("tattoo", "artist", "specializing", "@")):
                    return current
    return fallback or node


def block_name(block, handle: str) -> str | None:
    for tag in ("h2", "h3", "h4", "strong", "b"):
        found = block.find(tag) if hasattr(block, "find") else None
        if found:
            text = found.get_text(" ", strip=True)
            if text and "@" not in text and len(text) <= 100:
                return text
    text = block.get_text(" ", strip=True) if hasattr(block, "get_text") else ""
    text = re.sub(rf"@?{re.escape(handle)}", "", text, flags=re.I)
    bits = [part.strip(" |-–—") for part in re.split(r"[|•\n]", text) if part.strip()]
    for bit in bits:
        if 2 <= len(bit) <= 80 and not EMAIL_RE.search(bit) and "http" not in bit.lower():
            return bit
    return None


def public_contacts(block, page_url: str, handle: str) -> dict:
    text = block.get_text(" ", strip=True) if hasattr(block, "get_text") else ""
    emails = sorted({m.group(1).lower() for m in EMAIL_RE.finditer(text)})
    booking_urls: list[str] = []
    website_urls: list[str] = []
    if hasattr(block, "find_all"):
        for link in block.find_all("a", href=True):
            href = urljoin(page_url, link.get("href", "").strip())
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            if parsed.hostname in IG_HOSTS:
                continue
            label = link.get_text(" ", strip=True).lower()
            lower_href = href.lower()
            if any(word in label or word in lower_href for word in CONTACT_WORDS):
                if href not in booking_urls:
                    booking_urls.append(href)
            elif parsed.hostname != urlparse(page_url).hostname and href not in website_urls:
                website_urls.append(href)
    profile_url = f"https://www.instagram.com/{handle}/"
    if emails:
        score, best = 100, "public_artist_email"
    elif booking_urls:
        score, best = 85, "public_booking_or_contact_link"
    elif website_urls:
        score, best = 65, "public_artist_website"
    else:
        score, best = 40, "public_instagram_profile"
    return {
        "emails": emails,
        "booking_urls": booking_urls[:3],
        "website_urls": website_urls[:3],
        "instagram_url": profile_url,
        "contactability": score,
        "best_contact_method": best,
    }


def extract_artists(html: str, source: Source, fetched_at: datetime) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, dict] = {}

    def add(handle: str, block) -> None:
        clean = normalize_handle(handle)
        if not clean:
            return
        contacts = public_contacts(block, source.url, clean)
        row = {
            "username": clean,
            "name": block_name(block, clean),
            "profile_url": contacts["instagram_url"],
            "market": source.market,
            "activity_source": source.name,
            "activity_source_url": source.url,
            "event_start": source.event_start.isoformat(),
            "event_end": source.event_end.isoformat(),
            "activity_verified_at": fetched_at.isoformat(),
            "fresh_activity": True,
            "pain_fit": None,
            "pain_freshness_hours": None,
            "contact": contacts,
        }
        existing = found.get(clean)
        if not existing or contacts["contactability"] > existing["contact"]["contactability"]:
            found[clean] = row

    for link in soup.find_all("a", href=True):
        handle = instagram_handle_from_url(link.get("href", ""))
        if handle:
            add(handle, nearest_artist_block(link))

    # Some convention sites render handles as plain text rather than links.
    for text_node in soup.find_all(string=HANDLE_RE):
        for match in HANDLE_RE.finditer(str(text_node)):
            handle = normalize_handle(match.group(1))
            if handle:
                add(handle, nearest_artist_block(text_node))

    return list(found.values())


def merge_artist(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    sources = list(merged.get("activity_sources") or [
        {
            "name": merged.get("activity_source"),
            "url": merged.get("activity_source_url"),
            "event_start": merged.get("event_start"),
            "event_end": merged.get("event_end"),
            "market": merged.get("market"),
        }
    ])
    candidate = {
        "name": incoming.get("activity_source"),
        "url": incoming.get("activity_source_url"),
        "event_start": incoming.get("event_start"),
        "event_end": incoming.get("event_end"),
        "market": incoming.get("market"),
    }
    if candidate not in sources:
        sources.append(candidate)
    merged["activity_sources"] = sources
    if incoming.get("contact", {}).get("contactability", 0) > merged.get("contact", {}).get("contactability", 0):
        merged["contact"] = incoming["contact"]
    if not merged.get("name") and incoming.get("name"):
        merged["name"] = incoming["name"]
    return merged


def run(*, sources: tuple[Source, ...] = DEFAULT_SOURCES, now: datetime | None = None, timeout: float = 20.0) -> dict:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    artists: dict[str, dict] = {}
    errors: list[dict] = []
    source_metrics: list[dict] = []

    headers = {"User-Agent": "EmptyChair-Hunter/1.0 public-roster research; contact=tryemptychair.com"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for source in sources:
            if not source_is_fresh(source, today):
                source_metrics.append({"source": source.name, "status": "stale_skipped", "artists": 0})
                continue
            try:
                response = client.get(source.url)
                response.raise_for_status()
                rows = extract_artists(response.text, source, now)
            except Exception as exc:
                errors.append({"stage": "source_fetch", "source": source.name, "error": type(exc).__name__})
                source_metrics.append({"source": source.name, "status": "error", "artists": 0})
                continue
            source_metrics.append({"source": source.name, "status": "ok", "artists": len(rows)})
            for row in rows:
                username = row["username"]
                artists[username] = merge_artist(artists[username], row) if username in artists else row

    rows = list(artists.values())
    rows.sort(key=lambda row: (-row["contact"]["contactability"], row["username"]))
    contactable = sum(1 for row in rows if row["contact"]["contactability"] >= 40)
    direct_contact = sum(1 for row in rows if row["contact"]["contactability"] >= 85)
    return {
        "schema": "empty-chair-hunter-fresh-contact-bucket-v1",
        "generated_at": now.isoformat(),
        "freshness_policy": {
            "activity": "source event is current/upcoming; ended sources expire after 7 days",
            "source_horizon_days": 120,
            "pain": "separate signal; must remain <=72h before HOT/WARM use",
            "note": "fresh activity is not treated as evidence of cancellation pain",
        },
        "metrics": {
            "sources_configured": len(sources),
            "sources_ok": sum(1 for item in source_metrics if item["status"] == "ok"),
            "unique_artists": len(rows),
            "contactable_artists": contactable,
            "direct_contact_artists": direct_contact,
        },
        "source_metrics": source_metrics,
        "errors": errors,
        "artists": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="hunter-fresh-contact-bucket.json")
    args = parser.parse_args()
    result = run()
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m = result["metrics"]
    print(
        "hunter fresh contact bucket // "
        f"artists={m['unique_artists']} contactable={m['contactable_artists']} direct={m['direct_contact_artists']} "
        f"sources={m['sources_ok']}/{m['sources_configured']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
