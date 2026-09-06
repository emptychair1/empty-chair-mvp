"""Sprint 1 public-signal collector for Empty Chair Hunter.

Design goals:
- public web only
- HTTP first, no production-app dependency
- normalize Instagram-indexed search results into explainable signals
- deterministic rule matching and dedupe
- JSON output suitable for GitHub Actions artifacts and later DB ingestion
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from config import EXCLUSION_PHRASES, INTENT_PHRASES, SEARCH_QUERIES, TATTOO_TERMS

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 EmptyChairHunter/1.0"
)
TIMEOUT = 20.0
MAX_RESULTS_PER_QUERY = 12


@dataclass(frozen=True)
class Signal:
    id: str
    source: str
    query: str
    url: str
    username: str
    title: str
    snippet: str
    matched_phrase: str
    discovered_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def normalize_result_url(href: str) -> str:
    """Extract a real result URL from common search-engine redirect wrappers."""
    href = unescape(href or "").strip()
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


def instagram_username(url: str) -> str:
    try:
        parsed = urlparse(url)
        if "instagram.com" not in parsed.netloc.lower():
            return ""
        parts = [p for p in parsed.path.split("/") if p]
        if not parts:
            return ""
        # /p/, /reel/, /reels/ and /tv/ are media paths and do not contain username.
        if parts[0].lower() in {"p", "reel", "reels", "tv", "explore", "accounts"}:
            return ""
        return parts[0].lstrip("@").lower()
    except Exception:
        return ""


def detect_phrase(text: str) -> str:
    lower = text.lower()
    if any(ex in lower for ex in EXCLUSION_PHRASES):
        return ""
    for phrase in INTENT_PHRASES:
        if phrase in lower:
            return phrase
    return ""


def relevant(text: str, url: str) -> tuple[bool, str]:
    phrase = detect_phrase(text)
    if not phrase:
        return False, ""
    lower = text.lower()
    tattoo = any(term in lower for term in TATTOO_TERMS)
    instagram = "instagram.com" in url.lower()
    return bool(tattoo and instagram), phrase


def signal_id(url: str, phrase: str, snippet: str) -> str:
    raw = f"{url}|{phrase}|{snippet[:240]}".encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:32]


def parse_duckduckgo(html: str, query: str) -> list[Signal]:
    soup = BeautifulSoup(html, "lxml")
    signals: list[Signal] = []
    for result in soup.select(".result"):
        link = result.select_one(".result__a")
        if not link:
            continue
        url = normalize_result_url(link.get("href", ""))
        title = clean_text(link.get_text(" ", strip=True))
        snippet_node = result.select_one(".result__snippet")
        snippet = clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")
        combined = f"{title} {snippet}"
        ok, phrase = relevant(combined, url)
        if not ok:
            continue
        signals.append(
            Signal(
                id=signal_id(url, phrase, snippet),
                source="duckduckgo_html",
                query=query,
                url=url,
                username=instagram_username(url),
                title=title,
                snippet=snippet,
                matched_phrase=phrase,
                discovered_at=utc_now(),
            )
        )
    return signals[:MAX_RESULTS_PER_QUERY]


def parse_bing(html: str, query: str) -> list[Signal]:
    soup = BeautifulSoup(html, "lxml")
    signals: list[Signal] = []
    for result in soup.select("li.b_algo"):
        link = result.select_one("h2 a")
        if not link:
            continue
        url = normalize_result_url(link.get("href", ""))
        title = clean_text(link.get_text(" ", strip=True))
        snippet_node = result.select_one(".b_caption p")
        snippet = clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")
        combined = f"{title} {snippet}"
        ok, phrase = relevant(combined, url)
        if not ok:
            continue
        signals.append(
            Signal(
                id=signal_id(url, phrase, snippet),
                source="bing_html",
                query=query,
                url=url,
                username=instagram_username(url),
                title=title,
                snippet=snippet,
                matched_phrase=phrase,
                discovered_at=utc_now(),
            )
        )
    return signals[:MAX_RESULTS_PER_QUERY]


def fetch_search(client: httpx.Client, query: str) -> list[Signal]:
    encoded = httpx.QueryParams({"q": query})
    attempts = [
        (f"https://html.duckduckgo.com/html/?{encoded}", parse_duckduckgo),
        (f"https://www.bing.com/search?{encoded}", parse_bing),
    ]
    errors: list[str] = []
    for url, parser in attempts:
        try:
            response = client.get(url)
            response.raise_for_status()
            found = parser(response.text, query)
            if found:
                return found
        except Exception as exc:
            errors.append(f"{urlparse(url).netloc}: {type(exc).__name__}: {exc}")
    if errors:
        print(f"collector warning // {query} // {' | '.join(errors)}", file=sys.stderr)
    return []


def dedupe(signals: list[Signal]) -> list[Signal]:
    by_id: dict[str, Signal] = {}
    for signal in signals:
        by_id.setdefault(signal.id, signal)
    return list(by_id.values())


def collect(limit_queries: int | None = None) -> list[Signal]:
    queries = SEARCH_QUERIES[:limit_queries] if limit_queries else SEARCH_QUERIES
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    all_signals: list[Signal] = []
    with httpx.Client(headers=headers, timeout=TIMEOUT, follow_redirects=True) as client:
        for index, query in enumerate(queries, start=1):
            found = fetch_search(client, query)
            all_signals.extend(found)
            print(f"hunter // query {index}/{len(queries)} // +{len(found)} // {query}")
            time.sleep(0.8)
    return dedupe(all_signals)


def write_output(signals: list[Signal], path: Path) -> None:
    payload = {
        "schema": "empty-chair-hunter-signals-v1",
        "generated_at": utc_now(),
        "count": len(signals),
        "signals": [asdict(signal) for signal in signals],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="hunter-signals.json")
    parser.add_argument("--limit-queries", type=int, default=None)
    args = parser.parse_args()

    signals = collect(limit_queries=args.limit_queries)
    write_output(signals, Path(args.out))
    print(f"hunter // collected {len(signals)} unique public Instagram signals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
