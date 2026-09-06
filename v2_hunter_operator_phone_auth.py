"""Phone-number admin authorization for the Hunter operator console."""
from __future__ import annotations

import os

from fastapi import HTTPException, Request

import v2_app as core
import v2_hunter_operator as hunter_operator
from hunter.operator_auth import actor_identity, is_admin_identity, parse_phones


ADMIN_PHONES = parse_phones(os.getenv("EMPTY_CHAIR_ADMIN_PHONES", ""))


def is_admin_artist(artist: dict | None) -> bool:
    return is_admin_identity(
        artist,
        admin_emails=hunter_operator.ADMIN_EMAILS,
        admin_phones=ADMIN_PHONES,
    )


def admin_artist(request: Request):
    artist = core.current_artist(request)
    if not is_admin_artist(artist):
        raise HTTPException(404, "Not found")
    # Existing Sprint 9 decision routes record artist["email"] as the audit actor.
    # Preserve email when present, otherwise supply the normalized phone identity.
    if not str(artist.get("email") or "").strip():
        artist = dict(artist)
        artist["email"] = actor_identity(artist)
    return artist


# Existing route functions resolve this module global at request time, so replacing it
# upgrades the already-registered Sprint 9 routes without duplicating route definitions.
hunter_operator.admin_artist = admin_artist
