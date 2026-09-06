"""Pure Hunter operator admin identity helpers.

Kept free of FastAPI/production app imports so Hunter contract tests can validate
phone/email authorization without installing the web application dependencies.
"""
from __future__ import annotations


def normalize_phone(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return raw


def parse_emails(value: str) -> set[str]:
    return {
        item.strip().lower()
        for item in str(value or "").split(",")
        if item.strip()
    }


def parse_phones(value: str) -> set[str]:
    return {
        normalized
        for item in str(value or "").split(",")
        if (normalized := normalize_phone(item))
    }


def is_admin_identity(
    artist: dict | None,
    *,
    admin_emails: set[str],
    admin_phones: set[str],
) -> bool:
    if not artist:
        return False
    email = str(artist.get("email") or "").strip().lower()
    phone = normalize_phone(artist.get("phone"))
    return bool(
        (email and email in admin_emails)
        or (phone and phone in admin_phones)
    )


def actor_identity(artist: dict) -> str:
    email = str(artist.get("email") or "").strip().lower()
    if email:
        return email
    phone = normalize_phone(artist.get("phone"))
    return phone or str(artist.get("id") or "unknown")
