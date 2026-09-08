"""Credential-free public Reddit discovery for Founder Reddit Copilot."""
from __future__ import annotations

import html as html_lib
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, unquote, urlparse, parse_qs
from urllib.request import Request, urlopen

import v2_founder_reddit as radar

UA = "EmptyChairFounderRadar/2.1 (+https://tryemptychair.com)"
QUERIES = (
    'site:reddit.com/r/TattooArtists cancellation tattoo artist',
    'site:reddit.com/r/TattooArtists "last minute" tattoo opening',
    'site:reddit.com/r/TattooArtists "no show" tattoo artist',
    'site:reddit.com/r/TattooArtists booking deposit tattoo artist',
    'site:reddit.com/r/tattooing cancellation booking tattoo artist',
)
RSS_TERMS = ("cancellation", "no show", "last minute", "booking", "appointment", "deposit", "opening")
RSS_SUBS = ("TattooArtists", "tattooing", "tattoo")


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
        raw = unquote(parse_qs(urlparse(raw).query).get("q", [""])[0])
    if "reddit.com/r/" not in raw or "/comments/" not in raw:
        return ""
    raw = raw.split("&")[0]
    return raw if raw.startswith("http") else "https://www.reddit.com" + raw


def _rss_posts() -> list[dict]:
    posts = []
    for subreddit in RSS_SUBS:
        for term in RSS_TERMS:
            url = f"https://www.reddit.com/r/{subreddit}/search.rss?q={quote_plus(term)}&restrict_sr=on&sort=new&t=year"
            try:
                root = ET.fromstring(_get(url))
            except Exception as exc:
                print(f"Founder Reddit RSS failed // {subreddit}/{term}: {exc}", flush=True)
                continue
            for entry in root.findall("{*}entry"):
                title = _clean(entry.findtext("{*}title") or "")
                body = _clean(entry.findtext("{*}content") or entry.findtext("{*}summary") or "")
                link = ""
                for node in entry.findall("{*}link"):
                    href = node.attrib.get("href", "")
                    if "/comments/" in href:
                        link = href
                        break
                if not link:
                    continue
                parts = [p for p in urlparse(link).path.split("/") if p]
                pid = parts[3] if len(parts) > 3 and parts[2] == "comments" else str(abs(hash(link)))
                posts.append({
                    "id": pid,
                    "title": title,
                    "selftext": body,
                    "subreddit_name_prefixed": "r/" + subreddit,
                    "permalink": urlparse(link).path,
                    "url": link,
                    "num_comments": 0,
                    "created_utc": time.time() - 3 * 86400,
                    "ec_public_discovery": True,
                })
    return posts


def _google(query: str) -> list[dict]:
    page = _get("https://www.google.com/search?num=10&q=" + quote_plus(query))
    out = []
    for href, body in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.I | re.S):
        url = _reddit_url(href)
        if not url:
            continue
        title = _clean(body)
        if title and title.lower() not in {"reddit", "translate this result"}:
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
        "created_utc": time.time() - 30 * 86400,
        "ec_public_discovery": True,
    }


def _rank(posts: list[dict]) -> tuple[list[dict], bool]:
    seen = {}
    for post in posts:
        score, _label, angle = radar._score(post)
        score = min(100, score + 10)
        post["ec_score"] = score
        post["ec_label"] = "HIGH" if score >= 60 else "MEDIUM" if score >= 35 else "LOW"
        post["ec_angle"] = angle
        reply, mode = radar._suggest_reply(post)
        post["ec_reply"] = reply
        post["ec_reply_mode"] = mode
        seen[str(post.get("id") or post.get("url"))] = post
    ranked = sorted(seen.values(), key=lambda p: int(p.get("ec_score") or 0), reverse=True)
    return [p for p in ranked if int(p.get("ec_score") or 0) >= 25][:15], bool(seen)


def public_opportunities() -> tuple[list[dict], bool]:
    rss = _rss_posts()
    ranked, live = _rank(rss)
    if ranked:
        return ranked, live
    hits = []
    for query in QUERIES:
        for engine in (_bing, _google):
            try:
                batch = engine(query)
                if batch:
                    hits.extend(_normalize(x) for x in batch)
                    break
            except Exception as exc:
                print(f"Founder Reddit public discovery failed // {engine.__name__}: {exc}", flush=True)
    return _rank(hits)


_original = radar._opportunities


def _combined_opportunities():
    try:
        posts, live = _original()
        if posts:
            return posts, live
    except Exception as exc:
        print(f"Founder Reddit primary discovery failed: {exc}", flush=True)
    return public_opportunities()


radar._opportunities = _combined_opportunities
print("Founder Reddit public discovery loaded // Reddit RSS + web fallback", flush=True)
