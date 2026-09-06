"""Sprint 2: attach public signals to evidence-backed Instagram accounts.

No logins, private endpoints, outreach, or app/database imports. Unknown is
deliberately different from False. Discovery time is never post/activity time.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import socket
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from collect import USER_AGENT, clean_text, instagram_username, utc_now

SCHEMA = "empty-chair-hunter-artists-v1"
ACTIVE_DAYS = 90
MAX_PAGE_BYTES = 1_000_000
MAX_REQUESTS = 120
INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
STATES = dict(pair.split(":") for pair in (
    "AL:Alabama;AK:Alaska;AZ:Arizona;AR:Arkansas;CA:California;CO:Colorado;"
    "CT:Connecticut;DE:Delaware;FL:Florida;GA:Georgia;HI:Hawaii;ID:Idaho;"
    "IL:Illinois;IN:Indiana;IA:Iowa;KS:Kansas;KY:Kentucky;LA:Louisiana;"
    "ME:Maine;MD:Maryland;MA:Massachusetts;MI:Michigan;MN:Minnesota;"
    "MS:Mississippi;MO:Missouri;MT:Montana;NE:Nebraska;NV:Nevada;"
    "NH:New Hampshire;NJ:New Jersey;NM:New Mexico;NY:New York;"
    "NC:North Carolina;ND:North Dakota;OH:Ohio;OK:Oklahoma;OR:Oregon;"
    "PA:Pennsylvania;RI:Rhode Island;SC:South Carolina;SD:South Dakota;"
    "TN:Tennessee;TX:Texas;UT:Utah;VT:Vermont;VA:Virginia;WA:Washington;"
    "WV:West Virginia;WI:Wisconsin;WY:Wyoming;DC:District of Columbia"
).split(";"))


def profile_url(username: str) -> str:
    return f"https://www.instagram.com/{username}/"


def public_url(url: str) -> bool:
    """Reject credentials, non-web ports, and non-public DNS/IP destinations."""
    try:
        parsed = urlparse(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.port not in {None, 80, 443}):
            return False
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or
                                       (443 if parsed.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(a[4][0]).is_global for a in addresses)
    except (ValueError, OSError):
        return False


@dataclass
class Page:
    url: str
    html: str = ""
    error: str = ""


class PublicFetcher:
    """Bounded, cached, unauthenticated HTTP; validate every redirect hop."""

    def __init__(self, client: httpx.Client, *, max_requests: int = MAX_REQUESTS,
                 url_check: Callable[[str], bool] = public_url):
        self.client = client
        self.max_requests = max_requests
        self.url_check = url_check
        self.requests = 0
        self.cache: dict[str, Page] = {}

    def get(self, url: str) -> Page:
        if url in self.cache:
            return self.cache[url]
        original = url
        page = Page(url, error="redirect_limit")
        for _ in range(4):
            if not self.url_check(url):
                page = Page(url, error="unsafe_url_or_unresolved_host")
                break
            if self.requests >= self.max_requests:
                page = Page(url, error="request_budget_exhausted")
                break
            self.requests += 1
            try:
                with self.client.stream("GET", url, follow_redirects=False,
                                        headers={"User-Agent": USER_AGENT}) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            page = Page(url, error="invalid_redirect")
                            break
                        url = urljoin(url, location)
                        continue
                    if response.status_code != 200:
                        page = Page(url, error=f"http_{response.status_code}")
                        break
                    if "html" not in response.headers.get("content-type", "").lower():
                        page = Page(url, error="not_html")
                        break
                    body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=16384):
                        body.extend(chunk)
                        if len(body) > MAX_PAGE_BYTES:
                            break
                    if len(body) > MAX_PAGE_BYTES:
                        page = Page(url, error="page_too_large")
                    else:
                        page = Page(url, html=body.decode("utf-8", errors="replace"))
                    break
            except httpx.HTTPError:
                # Do not log URLs with query strings, response bodies, or credentials.
                page = Page(url, error="fetch_failed")
                break
        self.cache[original] = page
        return page


def types(node: dict) -> set[str]:
    value = node.get("@type", [])
    return {item for item in (value if isinstance(value, list) else [value]) if isinstance(item, str)}


def objects(value):
    """Walk only schema containers, not arbitrary nested/recommended accounts."""
    if isinstance(value, list):
        for item in value:
            yield from objects(item)
    elif isinstance(value, dict):
        yield value
        if "@graph" in value:
            yield from objects(value["@graph"])


@dataclass
class Context:
    identities: set[str] = field(default_factory=set)
    identity_source: str = ""
    text: str = ""
    entity_type: str = ""
    subject_text: str = ""
    address: dict = field(default_factory=dict)
    published_at: str | None = None


def parse_context(page: Page) -> Context:
    context = Context()
    if page.error:
        return context
    soup = BeautifulSoup(page.html, "lxml")
    title = clean_text(soup.title.get_text(" ")) if soup.title else ""
    metas = {tag.get("property") or tag.get("name"): tag.get("content", "")
             for tag in soup.select("meta[content]")}
    context.text = clean_text(" | ".join(filter(None, (
        title, metas.get("og:title"), metas.get("description"), metas.get("og:description"),
    ))))
    direct = instagram_username(page.url)
    host = urlparse(page.url).hostname
    if host in INSTAGRAM_HOSTS and re.search(
        r"log in to instagram|login . instagram|sign up . instagram", context.text, re.I
    ):
        return Context()
    if direct:
        context.identities.add(direct)
        context.identity_source = "instagram_profile_url"

    nodes = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            nodes.extend(objects(json.loads(script.string or script.get_text())))
        except (ValueError, TypeError, RecursionError):
            continue
    subjects = []
    for node in nodes:
        kind = types(node)
        if kind & {"ProfilePage", "WebPage"}:
            subjects.extend(objects(node.get("mainEntity", [])))
        elif kind & {"Article", "BlogPosting", "SocialMediaPosting", "VideoObject", "ImageObject"}:
            subjects.extend(objects(node.get("author", [])))
            if isinstance(node.get("datePublished"), str):
                context.published_at = node["datePublished"]
        elif kind & {"Person", "Organization", "LocalBusiness", "TattooParlor"}:
            subjects.append(node)
    # Multiple subjects must not donate one person's bio to another account.
    subject = subjects[0] if len(subjects) == 1 else None
    for item in subjects:
        urls = item.get("sameAs", [])
        urls = urls if isinstance(urls, list) else [urls]
        urls += [item.get("url", "")]
        for url in urls:
            username = instagram_username(url) if isinstance(url, str) else ""
            if username:
                context.identities.add(username)
                context.identity_source = context.identity_source or "structured_subject"
    if subject:
        context.entity_type = "individual" if "Person" in types(subject) else "studio" if (
            types(subject) & {"Organization", "LocalBusiness", "TattooParlor"}
        ) else ""
        context.subject_text = " | ".join(
            subject[k] for k in ("name", "description", "jobTitle")
            if isinstance(subject.get(k), str)
        )
        context.text += " | " + context.subject_text
        if isinstance(subject.get("address"), dict):
            context.address = subject["address"]

    # On media pages only use owner metadata, never mentions in captions/comments.
    if host in INSTAGRAM_HOSTS:
        for value in (title, metas.get("og:title", "")):
            match = re.search(r"\(@([A-Za-z0-9._]{1,30})\)", value)
            if match and instagram_username(profile_url(match[1].lower())):
                context.identities.add(match[1].lower())
                context.identity_source = context.identity_source or "instagram_owner_metadata"
    elif host not in INSTAGRAM_HOSTS and not context.identities:
        for tag in soup.select('a[href]'):
            username = instagram_username(urljoin(page.url, tag.get("href", "")))
            if username:
                context.identities.add(username)
        if context.identities:
            context.identity_source = "public_page_link"
    # Never use page body text (comments/recommendations) as profile context.
    if not context.published_at:
        context.published_at = metas.get("article:published_time") or None
    return context


def extract_location(context: Context) -> dict | None:
    address = context.address
    city, region, country = (address.get(k) for k in
                             ("addressLocality", "addressRegion", "addressCountry"))
    if isinstance(country, dict):
        country = country.get("name")
    if city and region and all(isinstance(v, str) for v in (city, region)):
        region_code = next((code for code, name in STATES.items()
                            if region in {code, name}), None)
        if country in {"US", "USA", "United States", "United States of America"}:
            country = "US"
        # An address without country can be ambiguous (e.g. CA); do not infer US.
        return {"city": city, "region": region_code or region,
                "country": country if isinstance(country, str) else None,
                "evidence": "structured_address"}
    state_pattern = "|".join(re.escape(v) for v in [*STATES, *STATES.values()])
    city_state = rf"\s*([A-Z][A-Za-z .'-]{{1,45}}),\s*({state_pattern})(?=\b|$)"
    match = re.search(r"(?:\bbased in\s+|\blocated in\s+|\blocation:\s*)" + city_state, context.text)
    if not match:
        match = re.search(r"(?:^|[|•\n])" + city_state, context.text)
    if match:
        city, state = match.groups()
        # Exclude a sentence fragment or travel announcement mistaken for a city.
        if re.search(r"\b(tattoo|guest|visit|travel|booking|artist|moving)\b", city, re.I):
            return None
        code = next(code for code, name in STATES.items() if state in {code, name})
        return {"city": city.strip(), "region": code, "country": "US",
                "evidence": match.group(0).strip(" |")}
    return None


def timestamp(value: str | None, now: datetime) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
        if parsed is None or parsed.tzinfo is None or parsed > now:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


def classify(context: Context, *, activity_at: datetime | None, now: datetime) -> dict:
    text = context.text.lower()
    excluded = re.search(
        r"\b(?:tattoo (?:collector|enthusiast|fan|supplies|supply|convention)|"
        r"tattoo equipment|meme (?:page|account)|not a tattoo artist)\b", text
    )
    artist = re.search(r"\b(?:tattoo artist|tattooer|tattooist)\b", text)
    studio = re.search(r"\b(?:tattoo (?:studio|shop|parlou?r)|our (?:artists|team))\b", text)
    individual = bool(artist and (context.entity_type == "individual" or re.search(
        r"\b(?:independent|individual|freelance|resident) tattoo artist\b|"
        r"\b(?:i am|i'm) (?:a |an )?tattoo|\b(?:my books|my clients)\b", text
    )))
    is_artist = False if excluded else True if artist else None
    account_type = "non_artist" if excluded else "individual" if individual else (
        "studio" if studio or context.entity_type == "studio" else "unknown"
    )
    booking = re.search(
        r"\b(?:book (?:an? |your )?(?:appointment|session)|"
        r"(?:dm|email|contact) (?:me |us )?(?:to book|for (?:bookings|appointments))|"
        r"(?:my )?books (?:are )?open|accepting (?:bookings|appointments)|"
        r"booking (?:link|inquiries|enquiries)|deposits? required)\b", text
    )
    closed = re.search(r"\b(?:not (?:currently )?accepting (?:bookings|appointments)|"
                       r"(?:books|bookings) (?:are )?closed|retired tattoo artist)\b", text)
    commercial = False if is_artist is False or closed else True if booking else None
    active = (activity_at >= now - timedelta(days=ACTIVE_DAYS)) if activity_at else None
    return {
        "is_tattoo_artist": is_artist, "account_type": account_type,
        "commercial_account": commercial,
        "active_account": active,
        "active_commercial_account": active if commercial is True else commercial,
        "last_activity_at": activity_at.isoformat() if activity_at else None,
        "classification_evidence": {
            "tattoo_artist": artist.group(0) if artist else None,
            "exclusion": excluded.group(0) if excluded else None,
            "commercial": booking.group(0) if booking else None,
            "closed": closed.group(0) if closed else None,
        },
        "location": extract_location(context),
    }


def resolve_signal(signal: dict, fetcher: PublicFetcher, now: datetime) -> dict:
    source = fetcher.get(signal["source_url"])
    context = parse_context(source)
    result = {"signal_id": signal["id"], "status": "UNRESOLVED", "account_id": None,
              "reason": source.error or "no_verified_identity"}
    if len(context.identities) != 1:
        if len(context.identities) > 1:
            result["reason"] = "ambiguous_accounts"
        return result
    username = next(iter(context.identities))
    identity_source = context.identity_source
    profile = source if instagram_username(source.url) == username else fetcher.get(profile_url(username))
    profile_context = parse_context(profile)
    if profile_context.identities and profile_context.identities != {username}:
        result["reason"] = "profile_identity_conflict"
        return result
    if profile_context.text and profile_context.identities == {username}:
        classification_context = profile_context
    elif context.identity_source == "structured_subject" and context.entity_type:
        classification_context = Context(text=context.subject_text, entity_type=context.entity_type,
                                         address=context.address)
    else:
        result["reason"] = profile.error or "profile_context_unavailable"
        return result
    activity_at = timestamp(context.published_at, now)
    data = classify(classification_context, activity_at=activity_at, now=now)
    status = "REJECTED" if data["is_tattoo_artist"] is False else (
        "RESOLVED" if data["is_tattoo_artist"] is True else "UNRESOLVED"
    )
    account_id = hashlib.sha256(f"instagram:{username}".encode()).hexdigest()[:32]
    return {**result, "status": status,
            "reason": "artist_evidence" if status == "RESOLVED" else (
                "non_artist_evidence" if status == "REJECTED" else "insufficient_artist_evidence"
            ),
            "account_id": account_id, "username": username, "profile_url": profile_url(username),
            "identity_evidence": {"kind": identity_source, "source_url": source.url},
            "profile_context": classification_context.text[:8000], **data}


def resolve_signals(signals: list[dict], fetcher: PublicFetcher, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    resolutions = []
    accounts = {}
    seen = set()
    for signal in signals:
        if not isinstance(signal, dict) or not all(isinstance(signal.get(k), str) and signal[k]
                                                  for k in ("id", "source_url")):
            raise ValueError("Every signal requires a nonempty string id and source_url")
        if signal["id"] in seen:
            continue
        seen.add(signal["id"])
        result = resolve_signal(signal, fetcher, now)
        resolutions.append(result)
        if not result["account_id"]:
            continue
        key = result["account_id"]
        if key not in accounts:
            accounts[key] = {k: v for k, v in result.items() if k != "signal_id"}
            accounts[key]["signals"] = []
        account = accounts[key]
        account["signals"].append({k: signal.get(k) for k in (
            "id", "source_url", "source", "query", "matched_phrase", "discovered_at"
        )})
        previous = timestamp(account.get("last_activity_at"), now)
        current = timestamp(result.get("last_activity_at"), now)
        if current and (previous is None or current > previous):
            for field_name in ("last_activity_at", "active_account", "active_commercial_account"):
                account[field_name] = result[field_name]
        # Contradictory classifications must be reviewed, not silently overwritten.
        if (account["is_tattoo_artist"] != result["is_tattoo_artist"]
                or account["account_type"] != result["account_type"]):
            account.update(status="UNRESOLVED", reason="conflicting_profile_evidence")
    return {"schema": SCHEMA, "generated_at": now.isoformat(),
            "input_count": len(signals), "unique_signal_count": len(resolutions),
            "account_count": len(accounts), "status_counts": dict(Counter(
                result["status"] for result in resolutions)),
            "request_count": fetcher.requests,
            "accounts": sorted(accounts.values(), key=lambda a: a["username"]),
            "resolutions": resolutions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="hunter-signals.json")
    parser.add_argument("--out", default="hunter-artists.json")
    parser.add_argument("--max-requests", type=int, default=MAX_REQUESTS)
    args = parser.parse_args()
    if args.max_requests < 0:
        parser.error("--max-requests must be nonnegative")
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "empty-chair-hunter-signals-v1" or not isinstance(payload.get("signals"), list):
        parser.error("Expected a Sprint 1 empty-chair-hunter-signals-v1 signals file")
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        result = resolve_signals(payload["signals"], PublicFetcher(client, max_requests=args.max_requests))
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"hunter // {result['account_count']} unique accounts // {result['status_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
