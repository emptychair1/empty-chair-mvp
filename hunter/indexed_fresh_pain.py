"""Find fresh Empty Chair pain signals for Hunter artists via public indexed web results.

This complements direct public-page inspection. It queries Bing's public RSS web-search
surface for artist-specific tattoo availability/cancellation language, then requires:
1) an artist identity match in the result text,
2) an Empty Chair pain phrase,
3) a result publication timestamp <=72h.

No login, cookies, private content, guessed contacts, challenge bypass, or outreach.
"""
from __future__ import annotations

import argparse
import email.utils
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from xml.etree import ElementTree as ET

import httpx

MAX_AGE_HOURS = 72.0
BING_RSS = "https://www.bing.com/search"

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
    raw = value.strip()
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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


def score(matches: dict[str, list[str]], age: float) -> int:
    base = 0
    if matches["disruption"]:
        base = max(base, 70)
    if matches["urgent_capacity"]:
        base = max(base, 60)
    if matches["capacity"]:
        base = max(base, 50)
    if not base:
        return 0
    return min(100, base + (15 if age <= 24 else 5))


def identity_matches(text: str, artist: dict) -> bool:
    hay = (text or "").lower()
    username = str(artist.get("username") or "").strip().lstrip("@").lower()
    if username and (username in hay or f"@{username}" in hay):
        return True
    name = re.sub(r"\s+", " ", str(artist.get("name") or "").strip().lower())
    return bool(name and len(name) >= 4 and name in hay)


def search_queries(artist: dict) -> list[str]:
    username = str(artist.get("username") or "").strip().lstrip("@")
    name = re.sub(r"\s+", " ", str(artist.get("name") or "").strip())
    pain = '(cancellation OR cancelled OR "last minute" OR opening OR available OR "books open" OR walk-in)'
    queries = []
    if username:
        queries.append(f'"{username}" tattoo {pain}')
    if name and name.lower() != username.lower():
        queries.append(f'"{name}" tattoo {pain}')
    return queries[:2]


def parse_rss(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    rows: list[dict] = []
    for item in root.findall(".//item"):
        rows.append({
            "title": item.findtext("title") or "",
            "link": item.findtext("link") or "",
            "description": item.findtext("description") or "",
            "published": item.findtext("pubDate") or "",
        })
    return rows


def inspect_artist(artist: dict, now: datetime, timeout: float) -> dict:
    evidence: list[dict] = []
    errors: list[dict] = []
    seen: set[str] = set()
    headers = {"User-Agent": "EmptyChair-Hunter/1.0 public-index research; contact=tryemptychair.com"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for query in search_queries(artist):
            try:
                response = client.get(BING_RSS, params={"q": query, "format": "rss"})
                response.raise_for_status()
                results = parse_rss(response.text)
            except Exception as exc:
                errors.append({"query": query, "error": type(exc).__name__})
                continue
            for row in results:
                link = str(row.get("link") or "").strip()
                if not link or link in seen:
                    continue
                seen.add(link)
                combined = " ".join([str(row.get("title") or ""), str(row.get("description") or ""), link])
                if not identity_matches(combined, artist):
                    continue
                matches = pain_matches(combined)
                if not any(matches.values()):
                    continue
                dt = parse_dt(str(row.get("published") or ""))
                age = age_hours(dt, now)
                if age is None or age > MAX_AGE_HOURS:
                    continue
                evidence.append({
                    "url": link,
                    "source_host": (urlparse(link).hostname or "").lower(),
                    "title": row.get("title"),
                    "published_at": dt.isoformat() if dt else None,
                    "age_hours": round(age, 2),
                    "matches": matches,
                    "pain_fit": score(matches, age),
                    "freshness_source": "indexed_result_pubDate",
                })
    evidence.sort(key=lambda x: (-int(x.get("pain_fit") or 0), float(x.get("age_hours") or 9999)))
    out = dict(artist)
    out["indexed_pain"] = {
        "status": "VERIFIED_PAIN" if evidence else "NO_VERIFIED_PAIN",
        "pain_fit": max((int(x.get("pain_fit") or 0) for x in evidence), default=None),
        "evidence": evidence[:8],
        "queries": len(search_queries(artist)),
        "errors": errors,
    }
    return out


def run(bucket: dict, *, now: datetime | None = None, workers: int = 16, timeout: float = 8.0) -> dict:
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
                artist["indexed_pain"] = {"status": "ERROR", "pain_fit": None, "evidence": [], "queries": 0, "errors": [{"error": "worker_failure"}]}
                checked.append(artist)
    verified = [a for a in checked if (a.get("indexed_pain") or {}).get("status") == "VERIFIED_PAIN"]
    verified.sort(key=lambda a: (-int((a.get("indexed_pain") or {}).get("pain_fit") or 0), a.get("username") or ""))
    direct = [a for a in verified if int((a.get("contact") or {}).get("contactability") or 0) >= 85]
    return {
        "schema": "empty-chair-hunter-indexed-fresh-pain-v1",
        "generated_at": now.isoformat(),
        "policy": {
            "pain_freshness_hours": 72,
            "identity": "result must match artist username or name",
            "source": "public indexed web results only; no login/private content",
        },
        "metrics": {
            "artists_input": len(artists),
            "artists_checked": len(checked),
            "verified_fresh_pain_leads": len(verified),
            "verified_direct_contact_leads": len(direct),
            "target_fresh_leads": 100,
        },
        "leads": verified,
        "artists": checked,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default="hunter-fresh-contact-bucket.json")
    parser.add_argument("--out", default="hunter-indexed-fresh-pain.json")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    bucket = json.loads(Path(args.bucket).read_text(encoding="utf-8"))
    result = run(bucket, workers=args.workers, timeout=args.timeout)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m = result["metrics"]
    print(f"hunter indexed fresh pain // input={m['artists_input']} checked={m['artists_checked']} verified={m['verified_fresh_pain_leads']} direct={m['verified_direct_contact_leads']} target={m['target_fresh_leads']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
