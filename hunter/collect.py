"""Sprint 1 public-signal collector for Empty Chair Hunter.

Design goals:
- public web only
- HTTP first, no production-app dependency
- find direct Instagram results OR public pages that resolve to an Instagram artist
- deterministic rule matching and dedupe
- JSON output suitable for GitHub Actions artifacts and later DB ingestion
"""
from __future__ import annotations

import argparse
import base64
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
    source_url: str
    instagram_url: str
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
    href = unescape(href or "").strip()
    if not href:
        return ""
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    if parsed.hostname in {"bing.com", "www.bing.com"} and parsed.path.startswith("/ck/"):
        encoded = qs.get("u", [""])[0]
        if encoded.startswith("a1"):
            try:
                token = encoded[2:]
                candidate = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
                if urlparse(candidate).scheme in {"http", "https"}:
                    return candidate
            except (ValueError, UnicodeError):
                pass
    for key in ("uddg", "url", "u", "q"):
        if key in qs and qs[key]:
            candidate = unquote(qs[key][0])
            if candidate.startswith("http"):
                return candidate
    return href if href.startswith("http") else ""


def instagram_username(url: str) -> str:
    try:
        parsed = urlparse(url)
        if (parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"instagram.com", "www.instagram.com", "m.instagram.com"}
                or parsed.username or parsed.password or parsed.port not in {None, 80, 443}):
            return ""
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) != 1 or parts[0].lower() in {
            "p", "reel", "reels", "tv", "explore", "accounts", "stories",
            "direct", "about", "developer", "developers", "legal", "web", "challenge",
        }:
            return ""
        username = parts[0].lower()
        if not re.fullmatch(r"[a-z0-9_](?:[a-z0-9._]{0,28}[a-z0-9_])?", username) or ".." in username:
            return ""
        return username
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


def relevant_text(text: str) -> tuple[bool, str]:
    phrase = detect_phrase(text)
    if not phrase:
        return False, ""
    lower = text.lower()
    return any(term in lower for term in TATTOO_TERMS), phrase


def find_instagram_url(html: str, fallback_text: str = "") -> str:
    soup = BeautifulSoup(html, "lxml")
    for link in soup.select('a[href*="instagram.com"]'):
        href = normalize_result_url(link.get("href", ""))
        username = instagram_username(href)
        if username:
            return f"https://www.instagram.com/{username}/"
    text = f"{fallback_text} {soup.get_text(' ', strip=True)[:12000]}"
    match = re.search(r"(?:instagram\s*[:\-]?\s*@|instagram\.com/)([A-Za-z0-9._]{1,30})", text, flags=re.I)
    if match:
        username = match.group(1).strip(".").lower()
        if username not in {"instagram", "tattoo", "com"} and instagram_username(f"https://www.instagram.com/{username}/"):
            return f"https://www.instagram.com/{username}/"
    return ""


def resolve_instagram(client: httpx.Client, source_url: str, text: str) -> str:
    if "instagram.com" in source_url.lower():
        username = instagram_username(source_url)
        if username:
            return f"https://www.instagram.com/{username}/"
        return source_url
    try:
        response = client.get(source_url)
        response.raise_for_status()
        return find_instagram_url(response.text, text)
    except Exception:
        # Search snippets sometimes expose @handles even when the page is unavailable.
        return find_instagram_url("", text)


def signal_id(source_url: str, instagram_url: str, phrase: str, snippet: str) -> str:
    raw = f"{source_url}|{instagram_url}|{phrase}|{snippet[:240]}".encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:32]


def result_to_signal(client: httpx.Client, *, source: str, query: str, url: str, title: str, snippet: str) -> Signal | None:
    combined = f"{title} {snippet}"
    ok, phrase = relevant_text(combined)
    if not ok:
        return None
    instagram_url = resolve_instagram(client, url, combined)
    if not instagram_url:
        return None
    return Signal(
        id=signal_id(url, instagram_url, phrase, snippet),
        source=source,
        query=query,
        source_url=url,
        instagram_url=instagram_url,
        username=instagram_username(instagram_url),
        title=title,
        snippet=snippet,
        matched_phrase=phrase,
        discovered_at=utc_now(),
    )


def parse_duckduckgo(client: httpx.Client, html: str, query: str) -> list[Signal]:
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
        signal = result_to_signal(client, source="duckduckgo_html", query=query, url=url, title=title, snippet=snippet)
        if signal:
            signals.append(signal)
    return signals[:MAX_RESULTS_PER_QUERY]


def parse_bing(client: httpx.Client, html: str, query: str) -> list[Signal]:
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
        signal = result_to_signal(client, source="bing_html", query=query, url=url, title=title, snippet=snippet)
        if signal:
            signals.append(signal)
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
            found = parser(client, response.text, query)
            if found:
                return found
        except Exception as exc:
            errors.append(f"{urlparse(url).netloc}: {type(exc).__name__}: {exc}")
    if errors:
        print(f"collector warning // {query} // {' | '.join(errors)}", file=sys.stderr)
    return []


def dedupe(signals: list[Signal]) -> list[Signal]:
    by_id: dict[str, Signal] = {}
    by_artist_phrase: set[tuple[str, str]] = set()
    output: list[Signal] = []
    for signal in signals:
        key = (signal.username, signal.matched_phrase)
        if signal.id in by_id or (signal.username and key in by_artist_phrase):
            continue
        by_id[signal.id] = signal
        if signal.username:
            by_artist_phrase.add(key)
        output.append(signal)
    return output


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
    print(f"hunter // collected {len(signals)} unique public tattoo-to-Instagram signals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
