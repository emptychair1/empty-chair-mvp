"""Authenticated Safari Story probe for Hunter.

Loads the local Safari session created by bootstrap_instagram_safari_session.py,
opens Instagram Story pages read-only, and classifies rendered Story text for
recovery intent. Session/cookie values are never printed.

This collector does not post, message, follow, like, or bypass verification.
Missing/inaccessible Stories are UNKNOWN rather than negative evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.safari.options import Options

from story_watch import classify_recovery

SCHEMA = "empty-chair-hunter-story-watch-safari-v1"
DEFAULT_SESSION = "hunter-instagram-safari-session.json"


def _load_session(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cookies = payload.get("cookies")
    if payload.get("schema") != "empty-chair-hunter-safari-session-v1" or not isinstance(cookies, list):
        raise SystemExit("Unsupported Hunter Safari session file")
    if not any(cookie.get("name") == "sessionid" for cookie in cookies if isinstance(cookie, dict)):
        raise SystemExit("Hunter Safari session does not contain an authenticated Instagram session")
    return payload


def _selenium_cookie(cookie: dict[str, Any]) -> dict[str, Any]:
    """Reduce a saved Safari cookie to fields Selenium accepts across Safari versions."""
    allowed = {"name", "value", "path", "domain", "secure", "httpOnly", "expiry", "sameSite"}
    cleaned = {k: v for k, v in cookie.items() if k in allowed and v is not None}
    if "expiry" in cleaned:
        try:
            cleaned["expiry"] = int(cleaned["expiry"])
        except (TypeError, ValueError):
            cleaned.pop("expiry", None)
    if cleaned.get("sameSite") not in ("Strict", "Lax", "None"):
        cleaned.pop("sameSite", None)
    return cleaned


def _install_session(driver, payload: dict[str, Any]) -> int:
    driver.get("https://www.instagram.com/")
    installed = 0
    for cookie in payload["cookies"]:
        if not isinstance(cookie, dict) or not cookie.get("name") or "value" not in cookie:
            continue
        cleaned = _selenium_cookie(cookie)
        try:
            driver.add_cookie(cleaned)
            installed += 1
        except WebDriverException:
            minimal = {k: cleaned[k] for k in ("name", "value", "path", "domain", "secure") if k in cleaned}
            try:
                driver.add_cookie(minimal)
                installed += 1
            except WebDriverException:
                continue
    driver.get("https://www.instagram.com/")
    time.sleep(2)
    return installed


def _visible_text(driver) -> str:
    """Return rendered human-facing text while excluding scripts/bootstrap payloads."""
    script = r"""
const badTags = new Set(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','SVG','PATH']);
const lines = [];
const seen = new Set();
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
let node;
while ((node = walker.nextNode())) {
  const parent = node.parentElement;
  if (!parent || badTags.has(parent.tagName)) continue;
  const style = window.getComputedStyle(parent);
  if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
  const rect = parent.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) continue;
  let text = (node.nodeValue || '').replace(/\s+/g, ' ').trim();
  if (!text || text.length > 500) continue;
  if (text.startsWith('{"require"') || text.startsWith('{"__bbox"') || text.startsWith('{"define"')) continue;
  if ((text.startsWith('{') || text.startsWith('[')) && text.includes('"gkxData"')) continue;
  if (!seen.has(text)) {
    seen.add(text);
    lines.push(text);
  }
  if (lines.length >= 250) break;
}
return lines.join('\n');
"""
    try:
        return str(driver.execute_script(script) or "").strip()
    except WebDriverException:
        return ""


def _auth_status(driver) -> tuple[bool, str]:
    url = driver.current_url.lower()
    if "/accounts/login" in url or "/auth_platform/" in url:
        return False, "redirected_to_login"
    names = {cookie.get("name") for cookie in driver.get_cookies()}
    if "sessionid" not in names:
        return False, "session_cookie_missing"
    return True, "authenticated"


def probe_username(driver, username: str, *, settle_seconds: float = 4.0) -> dict[str, Any]:
    clean = username.strip().lower().lstrip("@")
    story_url = f"https://www.instagram.com/stories/{clean}/"
    try:
        driver.get(story_url)
        time.sleep(settle_seconds)
        authenticated, auth_status = _auth_status(driver)
        if not authenticated:
            return {
                "username": clean,
                "ok": False,
                "status": "unknown_auth_failure",
                "current_url": driver.current_url,
                "intent_score": 0,
                "matches": [],
                "visible_text": "",
                "error": auth_status,
            }

        current_url = driver.current_url
        text = _visible_text(driver)
        lowered_url = current_url.lower()

        if f"/stories/{clean}/" not in lowered_url:
            return {
                "username": clean,
                "ok": True,
                "status": "unknown_no_viewable_story",
                "current_url": current_url,
                "intent_score": 0,
                "matches": [],
                "visible_text": text[:1000],
                "error": None,
            }

        if not text:
            return {
                "username": clean,
                "ok": True,
                "status": "unknown_story_text_unreadable",
                "current_url": current_url,
                "intent_score": 0,
                "matches": [],
                "visible_text": "",
                "error": None,
            }

        classification = classify_recovery(text)
        return {
            "username": clean,
            "ok": True,
            "status": "recovery_story_found" if classification["recovery"] else "story_visible_no_recovery_text",
            "current_url": current_url,
            "intent_score": classification["intent_score"],
            "matches": classification["matches"],
            "visible_text": text[:4000],
            "error": None,
        }
    except Exception as exc:
        return {
            "username": clean,
            "ok": False,
            "status": "unknown_browser_or_access_failure",
            "current_url": "",
            "intent_score": 0,
            "matches": [],
            "visible_text": "",
            "error": f"{exc.__class__.__name__}: {exc}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usernames", nargs="+")
    parser.add_argument(
        "--session",
        default=os.getenv("HUNTER_IG_SAFARI_SESSION_FILE", DEFAULT_SESSION),
        help="local Hunter Safari session JSON",
    )
    parser.add_argument("--out")
    parser.add_argument("--settle-seconds", type=float, default=4.0)
    args = parser.parse_args()

    session_path = Path(args.session)
    if not session_path.exists():
        raise SystemExit(f"Hunter Safari session file not found: {session_path}")
    payload = _load_session(session_path)

    driver = webdriver.Safari(options=Options())
    try:
        installed = _install_session(driver, payload)
        authenticated, auth_status = _auth_status(driver)
        if not authenticated:
            raise SystemExit(f"Saved Safari session could not be restored: {auth_status}")

        results = [probe_username(driver, name, settle_seconds=args.settle_seconds) for name in args.usernames]
        output = {
            "schema": SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "authenticated": True,
            "cookies_installed": installed,
            "count": len(results),
            "recovery_signal_count": sum(1 for r in results if r["status"] == "recovery_story_found"),
            "results": results,
        }
        rendered = json.dumps(output, indent=2, ensure_ascii=False)
        print(rendered)
        if args.out:
            Path(args.out).write_text(rendered + "\n", encoding="utf-8")
        return 0
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
