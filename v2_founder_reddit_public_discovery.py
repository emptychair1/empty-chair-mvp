"""Fast credential-free public Reddit discovery for Founder Reddit Copilot."""
from __future__ import annotations

import html as html_lib
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, unquote, urlparse, parse_qs
from urllib.request import Request, urlopen

import v2_founder_reddit as radar

UA = "EmptyChairFounderRadar/2.2 (+https://tryemptychair.com)"
RSS_TERMS = ("cancellation", "no show", "last minute", "booking", "appointment", "deposit", "opening")
RSS_SUBS = ("TattooArtists", "tattooing", "tattoo")
WEB_QUERIES = (
    'site:reddit.com/r/TattooArtists cancellation tattoo artist',
    'site:reddit.com/r/TattooArtists "last minute" tattoo opening',
    'site:reddit.com/r/TattooArtists "no show" tattoo artist',
    'site:reddit.com/r/TattooArtists booking deposit tattoo artist',
    'site:reddit.com/r/tattooing cancellation booking tattoo artist',
)


def _get(url: str, timeout: float = 2.0) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(req, timeout=timeout) as r:
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


def _rss_one(subreddit: str, term: str) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/search.rss?q={quote_plus(term)}&restrict_sr=on&sort=new&t=year"
    root = ET.fromstring(_get(url))
    posts = []
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


def _rss_posts() -> list[dict]:
    jobs = [(sub, term) for sub in RSS_SUBS for term in RSS_TERMS]
    posts: list[dict] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_rss_one, sub, term): (sub, term) for sub, term in jobs}
        for future in as_completed(futures):
            try:
                posts.extend(future.result())
            except Exception:
                pass
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


def _web_posts() -> list[dict]:
    hits: list[dict] = []
    jobs = [(engine, query) for query in WEB_QUERIES for engine in (_bing, _google)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(engine, query) for engine, query in jobs]
        for future in as_completed(futures):
            try:
                hits.extend(_normalize(x) for x in future.result())
            except Exception:
                pass
    return hits


def public_opportunities() -> tuple[list[dict], bool]:
    ranked, live = _rank(_rss_posts())
    if ranked:
        return ranked, live
    return _rank(_web_posts())


def _combined_opportunities():
    # Do not call the old sequential Reddit JSON path here. When Reddit blocks
    # anonymous server traffic it can stall this page for tens of seconds.
    # Public discovery is concurrent and bounded so the Founder page opens fast.
    return public_opportunities()


radar._opportunities = _combined_opportunities
print("Founder Reddit public discovery loaded // fast concurrent RSS + web fallback", flush=True)
