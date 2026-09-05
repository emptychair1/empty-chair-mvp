"""Safe phone signup boundary for Empty Chair 2.0.

Catches production-only failures in the phone-auth path, logs the traceback on Render,
and returns a branded diagnostic stage instead of FastAPI's generic 500 page.
"""
from __future__ import annotations

import hashlib
import secrets
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import Form
from fastapi.responses import RedirectResponse

import v2_app as core


def _drop_post(path: str):
    core.app.router.routes[:] = [
        r for r in core.app.router.routes
        if not (getattr(r, "path", None) == path and "POST" in set(getattr(r, "methods", set()) or set()))
    ]


_drop_post("/auth/phone")


def _failure(stage: str, exc: Exception):
    ref = secrets.token_hex(4).upper()
    print(f"[PHONE SIGNUP {ref}] stage={stage} {type(exc).__name__}: {exc}", flush=True)
    traceback.print_exc()
    return core.page(
        "Phone sign in",
        f'''<div class="error"><h1>PHONE SIGN-IN HIT A PROBLEM.</h1><p>stage........{stage}</p><p>reference....{ref}</p></div><p class="dim">Nothing was charged. Send us this screen so we can trace the exact failure.</p><a class="button" href="/auth/phone">TRY AGAIN</a>''',
    )


@core.app.post("/auth/phone")
def phone_signup_safe(name: str = Form(...), phone: str = Form(...)):
    stage = "normalize"
    try:
        phone = core.clean_phone(phone)
        if not phone or len("".join(c for c in phone if c.isdigit())) < 10:
            return core.page("Phone sign in", "<div class='error'>ENTER A VALID MOBILE NUMBER.</div><a class='button' href='/auth/phone'>TRY AGAIN</a>")

        stage = "find_artist"
        artist = core.one("SELECT * FROM artists WHERE phone=? ORDER BY created_at LIMIT 1", (phone,))

        stage = "save_artist"
        if artist:
            aid = artist["id"]
            core.run(
                "UPDATE artists SET name=?,verified=0,setup_state='VERIFY',updated_at=? WHERE id=?",
                (name.strip() or artist["name"], core.utcnow(), aid),
            )
        else:
            aid = secrets.token_hex(16)
            now = core.utcnow()
            core.run(
                "INSERT INTO artists(id,name,email,phone,verified,setup_state,created_at,updated_at) VALUES(?,?,?,?,0,'VERIFY',?,?)",
                (aid, name.strip() or "Tattoo Artist", "", phone, now, now),
            )

        stage = "save_code"
        code = f"{secrets.randbelow(1000000):06d}"
        digest = hashlib.sha256((code + core.SESSION_SECRET).encode()).hexdigest()
        exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        core.run(
            "INSERT INTO otp_codes(artist_id,code_hash,expires_at) VALUES(?,?,?) ON CONFLICT(artist_id) DO UPDATE SET code_hash=excluded.code_hash,expires_at=excluded.expires_at",
            (aid, digest, exp),
        )

        stage = "send_sms"
        sent = bool(core.send_sms(phone, f"EMPTY CHAIR // VERIFY\n\n{code}\n\nCode expires in 10 min."))
        print(f"[PHONE SIGNUP] verification transport sent={sent} to=***{phone[-4:]}", flush=True)

        stage = "session"
        response = RedirectResponse("/setup/verify", status_code=303)
        core.set_session(response, aid)
        return response
    except Exception as exc:
        return _failure(stage, exc)
