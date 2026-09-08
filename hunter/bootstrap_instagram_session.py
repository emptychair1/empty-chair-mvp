"""Create a reusable instagrapi session for Hunter from GitHub Actions secrets.

Credentials are read only from environment variables. The resulting session file
contains authentication material and must be encrypted before it leaves the runner.
"""
from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    username = os.environ.get("HUNTER_IG_USERNAME", "").strip()
    password = os.environ.get("HUNTER_IG_PASSWORD", "")
    verification_code = os.environ.get("HUNTER_IG_VERIFICATION_CODE", "").strip()
    out = Path(os.environ.get("HUNTER_IG_SESSION_OUT", "hunter-instagram-session.json"))

    if not username or not password:
        raise SystemExit("Missing HUNTER_IG_USERNAME or HUNTER_IG_PASSWORD")

    from instagrapi import Client

    client = Client()
    kwargs = {}
    if verification_code:
        kwargs["verification_code"] = verification_code

    client.login(username, password, **kwargs)
    client.dump_settings(out)

    if not out.exists() or out.stat().st_size == 0:
        raise SystemExit("Session file was not created")

    print(f"hunter instagram session bootstrap // ok user_id={client.user_id} file={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
