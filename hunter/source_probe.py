"""Fail-fast public-source freshness experiment for Hunter.

This probe does not feed production targeting. It measures whether public search can
surface recent tattoo cancellation/opening signals across Instagram, TikTok, Facebook,
X/Twitter, artist websites, booking pages, and the general web.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from config import EXCLUSION_PHRASES, TATTOO_TERMS

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36 EmptyChairHunter/1.0"
TIMEOUT = 15.0
MAX_RESULTS_PER_QUERY = 8

HIGH_INTENT = (
    "had a cancellation",
    "last minute cancellation",
    "client rescheduled",
    "had a no show",
    "spot opened up",
    "need to fill this spot",
    "available today",
    "opening tomorrow",
)

SOURCE_FAMILIES = {
    "instagram": ("site:instagram.com tattoo \"{phrase}\"",),
    "tiktok": ("site:tiktok.com tattoo \"{phrase}\"",),
    "facebook": ("site:facebook.com tattoo \"{phrase}\"",),
    "x": (
        "site:x.com tattoo \"{phrase}\"",
        "site:twitter.com tattoo \"{phrase}\"",
    ),
    "artist_web": (
        "\"tattoo artist\" \"{phrase}\" -site:instagram.com -site:tiktok.com -site:facebook.com -site:x.com -site:twitter.com",
    ),
    "booking_web": ("tattoo booking appointment \"{phrase}\"",),
    "general_web": ("tattoo \"{phrase}\"",),
}

MONTHS = {
    name.lower(): number for number, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1
    )
}
MONTHS.update({name[:3].lower(): number for name, number in list(MONTHS.items())})
MONTH_RE = "|".join(sorted((re.escape(name) for name in MONTHS), key=len, reverse=True))
ABS_DATE_RE = re.compile(rf"\b({MONTH_RE})\s+(\d{{1,2}}),?\s+(20\d{{2}})\b", re.I)
ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
RELATIVE_RE = re.compile(r"\b(\d{1,3})\s+(minute|hour|day)s?\s+ago\b", re.I)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_result_url(href: str) -> str:
    href = clean(href)
    if not href:
        return ""
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    for key in ("uddg", "url", "u", "q"):
        if key in qs and qs[key]:
            candidate = unquote(qs[key][0])
            if candidate.startswith("http"):
                return candidate
    return href if href.startswith("http") else ""


def relevant(text: str) -> bool:
    lower = text.lower()
    if any(term in lower for term in EXCLUSION_PHRASES):
        return False
    return any(term in lower for term in TATTOO_TERMS) and any(phrase in lower for phrase in HIGH_INTENT)


def publication_time(text: str, now: datetime) -> datetime | None:
    lower = text.lower()
    if "today" in lower:
        return now
    if "yesterday" in lower:
        return now - timedelta(days=1)
    relative = RELATIVE_RE.search(text)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2).lower()
        if unit == "minute":
            return now - timedelta(minutes=amount)
        if unit == "hour":
            return now - timedelta(hours=amount)
        return now - timedelta(days=amount)
    iso = ISO_DATE_RE.search(text)
    if iso:
        try:
            return datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)), 12, tzinfo=timezone.utc)
        except ValueError:
            return None
    absolute = ABS_DATE_RE.search(text)
    if absolute:
        try:
            month = MONTHS[absolute.group(1).lower()]
            return datetime(int(absolute.group(3)), month, int(absolute.group(2)), 12, tzinfo=timezone.utc)
        except (ValueError, KeyError):
            return None
    return None


def parse_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    for result in soup.select(".result"):
        link = result.select_one(".result__a")
        if not link:
            continue
        snippet = result.select_one(".result__snippet")
        rows.append({
            "url": normalize_result_url(link.get("href", "")),
            "title": clean(link.get_text(" ", strip=True)),
            "snippet": clean(snippet.get_text(" ", strip=True) if snippet else ""),
        })
    if rows:
        return rows[:MAX_RESULTS_PER_QUERY]
    for result in soup.select("li.b_algo"):
        link = result.select_one("h2 a")
        if not link:
            continue
        snippet = result.select_one(".b_caption p")
        rows.append({
            "url": normalize_result_url(link.get("href", "")),
            "title": clean(link.get_text(" ", strip=True)),
            "snippet": clean(snippet.get_text(" ", strip=True) if snippet else ""),
        })
    return rows[:MAX_RESULTS_PER_QUERY]


def search(client: httpx.Client, query: str) -> list[dict]:
    params = httpx.QueryParams({"q": query})
    for url in (f"https://html.duckduckgo.com/html/?{params}", f"https://www.bing.com/search?{params}"):
        try:
            response = client.get(url)
            response.raise_for_status()
            rows = parse_results(response.text)
            if rows:
                return rows
        except Exception:
            continue
    return []


def queries() -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for family, templates in SOURCE_FAMILIES.items():
        for phrase in HIGH_INTENT:
            for template in templates:
                output.append((family, template.format(phrase=phrase)))
    return output


def run(*, max_queries: int | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    work = queries()
    if max_queries is not None:
        work = work[:max_queries]
    hits: list[dict] = []
    seen: set[tuple[str, str]] = set()
    with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}, timeout=TIMEOUT, follow_redirects=True) as client:
        for index, (family, query) in enumerate(work, 1):
            for row in search(client, query):
                text = f"{row['title']} {row['snippet']}"
                if not relevant(text):
                    continue
                key = (family, row["url"])
                if not row["url"] or key in seen:
                    continue
                seen.add(key)
                published = publication_time(text, now)
                age_hours = None if published is None or published > now else round((now - published).total_seconds() / 3600, 2)
                hits.append({
                    "family": family,
                    "query": query,
                    **row,
                    "published_at": published.isoformat() if published else None,
                    "age_hours": age_hours,
                })
            print(f"hunter source probe // {index}/{len(work)} // {family}")
            time.sleep(0.1)

    by_family: dict[str, dict] = {}
    for family in SOURCE_FAMILIES:
        family_hits = [hit for hit in hits if hit["family"] == family]
        known = [hit for hit in family_hits if hit["age_hours"] is not None]
        by_family[family] = {
            "signals": len(family_hits),
            "known_date": len(known),
            "within_24h": sum(1 for hit in known if hit["age_hours"] <= 24),
            "within_72h": sum(1 for hit in known if hit["age_hours"] <= 72),
            "stale_over_72h": sum(1 for hit in known if hit["age_hours"] > 72),
            "unknown_date": len(family_hits) - len(known),
        }
    totals = Counter()
    for stats in by_family.values():
        totals.update(stats)
    fresh_72 = totals["within_72h"]
    verdict = "PUBLIC_SEARCH_HAS_FRESH_INVENTORY" if fresh_72 else "PUBLIC_SEARCH_TOO_STALE_OR_UNDATED"
    return {
        "schema": "empty-chair-hunter-source-probe-v1",
        "generated_at": now.isoformat(),
        "query_count": len(work),
        "signal_count": len(hits),
        "verdict": verdict,
        "totals": dict(totals),
        "by_family": by_family,
        "signals": sorted(hits, key=lambda hit: (hit["age_hours"] is None, hit["age_hours"] if hit["age_hours"] is not None else 10**9, hit["family"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="hunter-source-probe.json")
    parser.add_argument("--max-queries", type=int, default=None)
    args = parser.parse_args()
    result = run(max_queries=args.max_queries)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"hunter source probe // {result['verdict']} // {result['by_family']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
