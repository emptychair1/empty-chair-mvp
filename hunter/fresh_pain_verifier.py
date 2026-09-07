"""Verify <=72h Empty Chair pain for artists in Hunter's fresh contact bucket.

The contact bucket proves that an artist is current and reachable. This module adds a
separate, stricter layer: a lead is only VERIFIED_PAIN when a public page contains a
pain/capacity phrase and that same page has trustworthy freshness evidence <=72h.

No private data is inferred, no login is performed, and no outreach is sent.
"""
from __future__ import annotations

import argparse
import email.utils
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

MAX_AGE_HOURS = 72.0
DISRUPTION_PATTERNS = (
    r"\bcancell?ation\b", r"\bcancel(?:led|ed)\b", r"\bno[- ]show\b",
    r"\breschedul(?:e|ed|ing)\b", r"\bappointment fell through\b",
)
URGENT_CAPACITY_PATTERNS = (
    r"\bavailable (?:today|tomorrow|tonight)\b", r"\bopening (?:today|tomorrow|tonight)\b",
    r"\bfree (?:today|tomorrow|tonight)\b", r"\blast[- ]minute (?:spot|slot|appointment|opening)\b",
    r"\bspot (?:just )?opened(?: up)?\b", r"\bslot (?:just )?opened(?: up)?\b",
    r"\bappointment (?:just )?opened(?: up)?\b", r"\bwalk[- ]ins? (?:today|tomorrow|welcome|available)\b",
    r"\bgap in (?:my|the) schedule\b", r"\bneed to fill (?:this|a|the) (?:spot|slot|appointment)\b",
)
CAPACITY_PATTERNS = (
    r"\bopening this week\b", r"\bavailability this week\b",
    r"\bappointments? available this week\b", r"\bwalk[- ]in availability\b",
    r"\bspot available\b", r"\bslot available\b", r"\bbooks? open this week\b",
)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def age_hours(dt: datetime | None, now: datetime) -> float | None:
    if dt is None or dt > now:
        return None
    return (now - dt).total_seconds() / 3600.0


def pain_matches(text: str) -> dict[str, list[str]]:
    def hits(patterns: tuple[str, ...]) -> list[str]:
        out: list[str] = []
        for pattern in patterns:
            match = re.search(pattern, text or "", re.I)
            if match:
                out.append(match.group(0))
        return out
    return {
        "disruption": hits(DISRUPTION_PATTERNS),
        "urgent_capacity": hits(URGENT_CAPACITY_PATTERNS),
        "capacity": hits(CAPACITY_PATTERNS),
    }


def strongest_score(matches: dict[str, list[str]], age: float) -> int:
    base = 0
    if matches.get("disruption"):
        base = max(base, 70)
    if matches.get("urgent_capacity"):
        base = max(base, 60)
    if matches.get("capacity"):
        base = max(base, 50)
    if not base:
        return 0
    bonus = 15 if age <= 24 else 5 if age <= 72 else 0
    return min(100, base + bonus)


def page_timestamps(soup: BeautifulSoup, headers: httpx.Headers) -> list[tuple[datetime, str]]:
    candidates: list[tuple[datetime, str]] = []

    def add(value: str | None, source: str) -> None:
        dt = parse_dt(value)
        if dt:
            candidates.append((dt, source))

    for tag in soup.find_all("time"):
        add(tag.get("datetime"), "html_time")
    for name in (
        "article:published_time", "article:modified_time", "date", "datepublished",
        "datemodified", "last-modified", "last_modified",
    ):
        meta = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if meta:
            add(meta.get("content"), f"meta:{name}")

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        for item in stack:
            if not isinstance(item, dict):
                continue
            for key in ("datePublished", "dateModified", "uploadDate", "startDate"):
                add(item.get(key), f"jsonld:{key}")

    add(headers.get("last-modified"), "http:last-modified")
    return candidates


def public_urls(artist: dict) -> list[str]:
    contact = artist.get("contact") or {}
    urls: list[str] = []
    for key in ("booking_urls", "website_urls"):
        for value in contact.get(key) or []:
            url = str(value or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            host = (urlparse(url).hostname or "").lower()
            if host.endswith("instagram.com"):
                continue
            if url not in urls:
                urls.append(url)
    return urls[:6]


def inspect_url(client: httpx.Client, url: str, now: datetime) -> dict | None:
    response = client.get(url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower() and "xhtml" not in content_type.lower():
        return None
    soup = BeautifulSoup(response.text, "lxml")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:250000]
    matches = pain_matches(text)
    if not any(matches.values()):
        return None
    timestamps = page_timestamps(soup, response.headers)
    fresh: list[tuple[float, datetime, str]] = []
    for dt, source in timestamps:
        age = age_hours(dt, now)
        if age is not None and age <= MAX_AGE_HOURS:
            fresh.append((age, dt, source))
    if not fresh:
        return {
            "url": str(response.url),
            "status": "PAIN_TEXT_UNVERIFIED_FRESHNESS",
            "matches": matches,
            "timestamp_candidates": len(timestamps),
        }
    fresh.sort(key=lambda row: row[0])
    age, dt, source = fresh[0]
    return {
        "url": str(response.url),
        "status": "VERIFIED_PAIN",
        "matches": matches,
        "evidence_timestamp": dt.isoformat(),
        "freshness_source": source,
        "age_hours": round(age, 2),
        "pain_fit": strongest_score(matches, age),
    }


def inspect_artist(artist: dict, now: datetime, timeout: float) -> dict:
    urls = public_urls(artist)
    evidence: list[dict] = []
    errors: list[dict] = []
    headers = {"User-Agent": "EmptyChair-Hunter/1.0 public-business research; contact=tryemptychair.com"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for url in urls:
            try:
                hit = inspect_url(client, url, now)
            except Exception as exc:
                errors.append({"url": url, "error": type(exc).__name__})
                continue
            if hit:
                evidence.append(hit)
    verified = [item for item in evidence if item.get("status") == "VERIFIED_PAIN"]
    best = max((int(item.get("pain_fit") or 0) for item in verified), default=0)
    result = dict(artist)
    result["pain_verification"] = {
        "status": "VERIFIED_PAIN" if verified else "NO_VERIFIED_PAIN",
        "pain_fit": best if verified else None,
        "verified_evidence": verified,
        "unverified_evidence": [item for item in evidence if item.get("status") != "VERIFIED_PAIN"],
        "urls_checked": len(urls),
        "errors": errors,
    }
    return result


def run(bucket: dict, *, now: datetime | None = None, workers: int = 12, timeout: float = 10.0) -> dict:
    now = now or datetime.now(timezone.utc)
    artists = list(bucket.get("artists") or [])
    checked: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(inspect_artist, artist, now, timeout): artist for artist in artists}
        for future in as_completed(futures):
            try:
                checked.append(future.result())
            except Exception:
                artist = dict(futures[future])
                artist["pain_verification"] = {
                    "status": "ERROR", "pain_fit": None, "verified_evidence": [],
                    "unverified_evidence": [], "urls_checked": 0, "errors": [{"error": "worker_failure"}],
                }
                checked.append(artist)

    checked.sort(key=lambda row: (
        0 if (row.get("pain_verification") or {}).get("status") == "VERIFIED_PAIN" else 1,
        -int((row.get("pain_verification") or {}).get("pain_fit") or 0),
        -int((row.get("contact") or {}).get("contactability") or 0),
        row.get("username") or "",
    ))
    verified = [row for row in checked if (row.get("pain_verification") or {}).get("status") == "VERIFIED_PAIN"]
    direct_verified = [row for row in verified if int((row.get("contact") or {}).get("contactability") or 0) >= 85]
    return {
        "schema": "empty-chair-hunter-fresh-pain-leads-v1",
        "generated_at": now.isoformat(),
        "policy": {
            "artist_activity": "must come from fresh-contact bucket",
            "pain": "phrase plus trustworthy page timestamp <=72h",
            "no_timestamp": "pain text is retained as unverified and does not count as a fresh pain lead",
        },
        "metrics": {
            "artists_input": len(artists),
            "artists_checked": len(checked),
            "verified_fresh_pain_leads": len(verified),
            "verified_direct_contact_leads": len(direct_verified),
            "target_fresh_leads": 100,
        },
        "leads": verified,
        "artists": checked,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default="hunter-fresh-contact-bucket.json")
    parser.add_argument("--out", default="hunter-fresh-pain-leads.json")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    bucket = json.loads(Path(args.bucket).read_text(encoding="utf-8"))
    result = run(bucket, workers=args.workers, timeout=args.timeout)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m = result["metrics"]
    print(
        "hunter fresh pain verifier // "
        f"input={m['artists_input']} checked={m['artists_checked']} "
        f"verified={m['verified_fresh_pain_leads']} direct={m['verified_direct_contact_leads']} "
        f"target={m['target_fresh_leads']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
