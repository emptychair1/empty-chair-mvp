"""Phone-number admin authorization for the Hunter operator console."""
from __future__ import annotations

import os

from fastapi import HTTPException, Request

import v2_app as core
import v2_hunter_operator as hunter_operator


def normalize_phone(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return core.clean_phone(raw)


ADMIN_PHONES = {
    normalize_phone(phone)
    for phone in os.getenv("EMPTY_CHAIR_ADMIN_PHONES", "").split(",")
    if normalize_phone(phone)
}


def is_admin_artist(artist: dict | None) -> bool:
    if not artist:
        return False
    email = str(artist.get("email") or "").strip().lower()
    phone = normalize_phone(artist.get("phone"))
    return bool(
        (email and email in hunter_operator.ADMIN_EMAILS)
        or (phone and phone in ADMIN_PHONES)
    )


def actor_identity(artist: dict) -> str:
    email = str(artist.get("email") or "").strip().lower()
    if email:
        return email
    phone = normalize_phone(artist.get("phone"))
    return phone or str(artist.get("id") or "unknown")


def admin_artist(request: Request):
    artist = core.current_artist(request)
    if not is_admin_artist(artist):
        raise HTTPException(404, "Not found")
    return artist


# Existing route functions resolve this module global at request time, so replacing it
# upgrades the already-registered Sprint 9 routes without duplicating route definitions.
hunter_operator.admin_artist = admin_artist
