"""Resolve a public Instagram post permalink to its visibly displayed username.

Hunter uses this only as a fallback when the official Meta hashtag API returns a
fresh post without an author field. The resolver never logs in, never reuses
session cookies, and never attempts to bypass Instagram challenges. It fails
closed when the public page is unavailable or OCR confidence is insufficient.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

USERNAME_RE = re.compile(r"(?<![A-Za-z0-9._])@?([A-Za-z0-9._]{1,30})(?![A-Za-z0-9._])")
RESERVED = {
    "instagram", "meta", "follow", "following", "followers", "likes", "like",
    "comment", "comments", "share", "login", "log", "sign", "signup", "reel",
    "reels", "post", "posts", "explore", "home", "more", "see", "translation",
}


@dataclass
class Resolution:
    permalink: str
    status: str
    username: str | None = None
    confidence: float = 0.0
    method: str | None = None
    reason: str | None = None


def validate_permalink(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname not in {"instagram.com", "www.instagram.com"}:
        raise ValueError("permalink must be an https://www.instagram.com/... URL")
    if not (parsed.path.startswith("/p/") or parsed.path.startswith("/reel/") or parsed.path.startswith("/tv/")):
        raise ValueError("permalink must point to an Instagram post or reel")
    return value.strip()


def candidate_usernames(text: str) -> list[str]:
    candidates: list[str] = []
    for match in USERNAME_RE.finditer(text or ""):
        value = match.group(1).strip("._").lower()
        if not value or value in RESERVED or value.isdigit():
            continue
        if value not in candidates:
            candidates.append(value)
    return candidates


def choose_username(text: str) -> tuple[str | None, float]:
    """Choose a conservative username candidate from visible header/OCR text."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for line in lines[:8]:
        # Instagram's post header normally puts the username on its own early line.
        raw = line.lstrip("@").strip()
        if re.fullmatch(r"[A-Za-z0-9._]{1,30}", raw) and raw.lower() not in RESERVED and not raw.isdigit():
            return raw.lower(), 0.95
    candidates = candidate_usernames("\n".join(lines[:12]))
    if len(candidates) == 1:
        return candidates[0], 0.80
    return None, 0.0


def _ocr(image_path: str) -> str:
    if not shutil.which("tesseract"):
        raise RuntimeError("tesseract executable is not installed")
    proc = subprocess.run(
        ["tesseract", image_path, "stdout", "--psm", "6"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "tesseract failed")
    return proc.stdout


def resolve(permalink: str, *, timeout_ms: int = 15000, headless: bool = True) -> Resolution:
    permalink = validate_permalink(permalink)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return Resolution(permalink, "unresolved", reason="playwright_not_installed")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
            response = page.goto(permalink, wait_until="domcontentloaded", timeout=timeout_ms)
            if response is None or response.status >= 400:
                browser.close()
                return Resolution(permalink, "unresolved", reason="public_page_unavailable")

            page.wait_for_timeout(1200)
            visible_text = page.locator("body").inner_text(timeout=5000)
            lower = visible_text.lower()
            if any(marker in lower for marker in ("log in to instagram", "login • instagram", "challenge_required", "please wait a few minutes")):
                browser.close()
                return Resolution(permalink, "unresolved", reason="login_or_challenge_present")

            username, confidence = choose_username(visible_text)
            if username and confidence >= 0.90:
                browser.close()
                return Resolution(permalink, "resolved", username, confidence, "visible_text")

            with tempfile.TemporaryDirectory(prefix="hunter-ig-") as tmp:
                shot = str(Path(tmp) / "header.png")
                # Only capture the top of the public page where the author handle is displayed.
                page.screenshot(path=shot, clip={"x": 0, "y": 0, "width": 390, "height": 260})
                browser.close()
                ocr_text = _ocr(shot)
                username, confidence = choose_username(ocr_text)
                if username and confidence >= 0.80:
                    return Resolution(permalink, "resolved", username, confidence, "ocr")
                return Resolution(permalink, "unresolved", reason="username_not_confidently_visible")
    except Exception as exc:
        return Resolution(permalink, "unresolved", reason=f"resolver_error:{type(exc).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("permalink")
    parser.add_argument("--out", default=None)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    result = resolve(args.permalink, headless=not args.headed)
    payload = json.dumps(asdict(result), indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result.status == "resolved" else 2


if __name__ == "__main__":
    raise SystemExit(main())
