"""Fail-fast hashtag discovery probe for Hunter.

Measures whether public/indexed hashtag surfaces expose recent tattoo opening/cancellation
inventory. This is diagnostic only: no authenticated scraping and no production targeting.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128 Safari/537.36 EmptyChairHunter/1.0"
TIMEOUT = 15.0
MAX_RESULTS_PER_QUERY = 10

HASHTAGS = (
    "tattooopenings",
    "tattoocancellation",
    "tattoocancellations",
    "tattooavailability",
    "lastminutetattoo",
    "tattooappointment",
    "tattoobooking",
    "walkintattoo",
    "tattooartistavailable",
)

PLATFORMS = {
    "instagram_hashtag": (
        "site:instagram.com #{tag}",
        "site:instagram.com tattoo #{tag}",
    ),
    "tiktok_hashtag": (
        "site:tiktok.com #{tag}",
        "site:tiktok.com tattoo #{tag}",
    ),
}

MONTHS = {
    name.lower(): number
    for number, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
        1,
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
            return datetime(
                int(absolute.group(3)), MONTHS[absolute.group(1).lower()], int(absolute.group(2)), 12, tzinfo=timezone.utc
            )
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


def queries() -> list[tuple[str, str, str]]:
    output: list[tuple[str, str, str]] = []
    for platform, templates in PLATFORMS.items():
        for tag in HASHTAGS:
            for template in templates:
                output.append((platform, tag, template.format(tag=tag)))
    return output


def run(*, max_queries: int | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    work = queries()
    if max_queries is not None:
        work = work[:max_queries]

    hits: list[dict] = []
    seen: set[tuple[str, str]] = set()
    with httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=TIMEOUT,
        follow_redirects=True,
    ) as client:
        for index, (platform, tag, query) in enumerate(work, 1):
            for row in search(client, query):
                text = f"{row['title']} {row['snippet']}".lower()
                if "tattoo" not in text and tag not in text.replace("#", ""):
                    continue
                key = (platform, row["url"])
                if not row["url"] or key in seen:
                    continue
                seen.add(key)
                published = publication_time(text, now)
                age_hours = None if published is None or published > now else round((now - published).total_seconds() / 3600, 2)
                hits.append({
                    "platform": platform,
                    "hashtag": tag,
                    "query": query,
                    **row,
                    "published_at": published.isoformat() if published else None,
                    "age_hours": age_hours,
                })
            print(f"hunter hashtag probe // {index}/{len(work)} // {platform} // #{tag}")
            time.sleep(0.1)

    by_platform: dict[str, dict] = {}
    for platform in PLATFORMS:
        platform_hits = [hit for hit in hits if hit["platform"] == platform]
        known = [hit for hit in platform_hits if hit["age_hours"] is not None]
        by_platform[platform] = {
            "signals": len(platform_hits),
            "known_date": len(known),
            "within_24h": sum(1 for hit in known if hit["age_hours"] <= 24),
            "within_72h": sum(1 for hit in known if hit["age_hours"] <= 72),
            "stale_over_72h": sum(1 for hit in known if hit["age_hours"] > 72),
            "unknown_date": len(platform_hits) - len(known),
        }

    by_hashtag: dict[str, dict] = {}
    for tag in HASHTAGS:
        tag_hits = [hit for hit in hits if hit["hashtag"] == tag]
        known = [hit for hit in tag_hits if hit["age_hours"] is not None]
        by_hashtag[tag] = {
            "signals": len(tag_hits),
            "within_24h": sum(1 for hit in known if hit["age_hours"] <= 24),
            "within_72h": sum(1 for hit in known if hit["age_hours"] <= 72),
            "unknown_date": len(tag_hits) - len(known),
        }

    totals = Counter()
    for stats in by_platform.values():
        totals.update(stats)
    verdict = "HASHTAGS_HAVE_FRESH_INVENTORY" if totals["within_72h"] else "HASHTAGS_TOO_STALE_OR_UNDATED"
    return {
        "schema": "empty-chair-hunter-hashtag-probe-v1",
        "generated_at": now.isoformat(),
        "query_count": len(work),
        "signal_count": len(hits),
        "verdict": verdict,
        "totals": dict(totals),
        "by_platform": by_platform,
        "by_hashtag": by_hashtag,
        "signals": sorted(
            hits,
            key=lambda hit: (
                hit["age_hours"] is None,
                hit["age_hours"] if hit["age_hours"] is not None else 10**9,
                hit["platform"],
                hit["hashtag"],
            ),
        ),
    }


def markdown_summary(result: dict) -> str:
    lines = [
        "## Hunter hashtag freshness probe",
        "",
        f"**Verdict:** `{result['verdict']}`",
        "",
        "| Platform | Signals | <=24h | <=72h | Stale | Unknown date |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for platform, stats in result["by_platform"].items():
        lines.append(
            f"| {platform} | {stats['signals']} | {stats['within_24h']} | {stats['within_72h']} | {stats['stale_over_72h']} | {stats['unknown_date']} |"
        )
    lines.extend(["", "### Hashtags", "", "| Hashtag | Signals | <=24h | <=72h | Unknown date |", "|---|---:|---:|---:|---:|"])
    for tag, stats in result["by_hashtag"].items():
        lines.append(f"| #{tag} | {stats['signals']} | {stats['within_24h']} | {stats['within_72h']} | {stats['unknown_date']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="hunter-hashtag-probe.json")
    parser.add_argument("--summary-out", default=None)
    parser.add_argument("--max-queries", type=int, default=None)
    args = parser.parse_args()
    result = run(max_queries=args.max_queries)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.summary_out:
        Path(args.summary_out).write_text(markdown_summary(result), encoding="utf-8")
    print(f"hunter hashtag probe // {result['verdict']} // {result['by_platform']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
