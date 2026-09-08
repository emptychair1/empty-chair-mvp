"""Credential-free public Reddit discovery for Founder Reddit Copilot.

Uses public web-search result pages (Google/Bing HTML) to discover Reddit threads,
then normalizes them into the existing copilot shape. No Reddit developer account,
OAuth, Devvit deployment, or autoposting is required.
"""
from __future__ import annotations

import html as html_lib
import re
import time
from urllib.parse import quote_plus, unquote, urlparse, parse_qs
from urllib.request import Request, urlopen

import v2_founder_reddit as radar

UA = "Mozilla/5.0 (compatible; EmptyChairFounderRadar/2.0; +https://tryemptychair.com)"
QUERIES = (
    'site:reddit.com/r/TattooArtists cancellation tattoo artist',
    'site:reddit.com/r/TattooArtists "last minute" tattoo opening',
    'site:reddit.com/r/TattooArtists "no show" tattoo artist',
    'site:reddit.com/r/TattooArtists booking deposit tattoo artist',
    'site:reddit.com/r/tattooing cancellation booking tattoo artist',
)


def _get(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(req, timeout=6) as r:
        return r.read().decode("utf-8", "ignore")


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return " ".join(html_lib.unescape(s).split())


def _reddit_url(raw: str) -> str:
    raw = html_lib.unescape(raw)
    if raw.startswith("/url?"):
        q = parse_qs(urlparse(raw).query).get("q", [""])[0]
        raw = unquote(q)
    if "reddit.com/r/" not in raw or "/comments/" not in raw:
        return ""
    raw = raw.split("&")[0]
    return raw if raw.startswith("http") else "https://www.reddit.com" + raw


def _google(query: str) -> list[dict]:
    page = _get("https://www.google.com/search?num=10&q=" + quote_plus(query))
    out = []
    for href, body in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.I | re.S):
        url = _reddit_url(href)
        if not url:
            continue
        title = _clean(body)
        if not title or title.lower() in {"reddit", "translate this result"}:
            continue
        out.append({"url": url, "title": title})
    return out


def _bing(query: str) -> list[dict]:
    page = _get("https://www.bing.com/search?q=" + quote_plus(query))
    out = []
    for href, title in re.findall(r'<h2>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.I | re.S):
        url = _reddit_url(href)
        if url:
            out.append({"url": url, "title": _clean(title)})
    return out


def _normalize(hit: dict) -> dict:
    url = hit["url"]
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    subreddit = parts[1] if len(parts) > 1 and parts[0] == "r" else "TattooArtists"
    pid = parts[3] if len(parts) > 3 and parts[2] == "comments" else str(abs(hash(url)))
    return {
        "id": pid,
        "title": hit.get("title") or "Reddit conversation",
        "selftext": "",
        "subreddit_name_prefixed": "r/" + subreddit,
        "permalink": parsed.path,
        "url": url,
        "num_comments": 0,
        # Search engines prioritize indexed public pages; keep age neutral rather than inventing it.
        "created_utc": time.time() - 46 * 86400,
        "ec_public_discovery": True,
    }


def public_opportunities() -> tuple[list[dict], bool]:
    seen = {}
    any_search = False
    for query in QUERIES:
        hits = []
        for engine in (_google, _bing):
            try:
                hits = engine(query)
                any_search = True
                if hits:
                    break
            except Exception as exc:
                print(f"Founder Reddit public discovery failed // {engine.__name__}: {exc}", flush=True)
        for hit in hits:
            post = _normalize(hit)
            score, label, angle = radar._score(post)
            # Search discovery itself is a relevance signal, but never fabricate recency/comments.
            score = min(100, score + 20)
            post["ec_score"] = score
            post["ec_label"] = "HIGH" if score >= 60 else "MEDIUM" if score >= 35 else "LOW"
            post["ec_angle"] = angle
            reply, mode = radar._suggest_reply(post)
            post["ec_reply"] = reply
            post["ec_reply_mode"] = mode
            seen[post["id"]] = post
    ranked = sorted(seen.values(), key=lambda p: int(p.get("ec_score") or 0), reverse=True)
    return [p for p in ranked if int(p.get("ec_score") or 0) >= 25][:15], any_search


_original = radar._opportunities


def _combined_opportunities():
    # First use any official/cached/anonymous Reddit path already available.
    try:
        posts, live = _original()
        if posts:
            return posts, live
    except Exception as exc:
        print(f"Founder Reddit primary discovery failed: {exc}", flush=True)
    # Then use credential-free public web discovery. User never has to search manually.
    return public_opportunities()


radar._opportunities = _combined_opportunities
print("Founder Reddit public discovery loaded // no Reddit credentials required", flush=True)
