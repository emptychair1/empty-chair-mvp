"""Create a reusable instagrapi session for Hunter.

Credentials are read only from environment variables. A stable pre-auth client
settings file is persisted locally so Instagram sees the same device identity
across manual challenge approvals and retries. The authenticated session output
contains sensitive material and must be encrypted before it leaves the machine.
"""
from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    username = os.environ.get("HUNTER_IG_USERNAME", "").strip()
    password = os.environ.get("HUNTER_IG_PASSWORD", "")
    verification_code = os.environ.get("HUNTER_IG_VERIFICATION_CODE", "").strip()
    out = Path(os.environ.get("HUNTER_IG_SESSION_OUT", "hunter-instagram-session.json"))
    device_settings = Path(
        os.environ.get("HUNTER_IG_DEVICE_SETTINGS", "hunter-instagram-device.json")
    )

    if not username or not password:
        raise SystemExit("Missing HUNTER_IG_USERNAME or HUNTER_IG_PASSWORD")

    from instagrapi import Client

    client = Client()

    if device_settings.exists() and device_settings.stat().st_size > 0:
        client.load_settings(device_settings)
        print(f"hunter instagram bootstrap // reusing device settings from {device_settings}")
    else:
        # Persist the freshly generated device UUIDs/settings before the first
        # login attempt. If Instagram requires a native approval, the retry can
        # reuse this exact identity instead of looking like a brand-new device.
        client.dump_settings(device_settings)
        print(f"hunter instagram bootstrap // created device settings at {device_settings}")

    kwargs = {}
    if verification_code:
        kwargs["verification_code"] = verification_code

    try:
        client.login(username, password, **kwargs)
    except Exception:
        # Preserve any client-side settings updates made during the attempt while
        # keeping the same device identifiers for the next legitimate retry.
        client.dump_settings(device_settings)
        raise

    client.dump_settings(out)

    if not out.exists() or out.stat().st_size == 0:
        raise SystemExit("Session file was not created")

    print(f"hunter instagram session bootstrap // ok user_id={client.user_id} file={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
