"""Resilient SMS transport for Empty Chair 2.0.

Supports the environment variable names used by earlier Empty Chair deploys and
prevents a Twilio delivery error from turning signup into a 500 response.
"""
from __future__ import annotations

import base64
import os
import urllib.error
import urllib.parse
import urllib.request

import v2_app as core

SID = os.getenv("TWILIO_ACCOUNT_SID", "") or os.getenv("TWILIO_SID", "")
TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "") or os.getenv("TWILIO_TOKEN", "")
FROM = (
    os.getenv("TWILIO_FROM_NUMBER", "")
    or os.getenv("TWILIO_PHONE_NUMBER", "")
    or os.getenv("TWILIO_NUMBER", "")
    or os.getenv("SMS_FROM_NUMBER", "")
)
MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")


def send_sms(to: str | None, text: str) -> bool:
    if not to:
        return False
    if not (SID and TOKEN and (FROM or MESSAGING_SERVICE_SID)):
        print(
            "[SMS disabled] Twilio config incomplete: "
            f"sid={bool(SID)} token={bool(TOKEN)} sender={bool(FROM or MESSAGING_SERVICE_SID)}",
            flush=True,
        )
        return False

    auth = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    fields = {"To": to, "Body": text}
    if MESSAGING_SERVICE_SID:
        fields["MessagingServiceSid"] = MESSAGING_SERVICE_SID
    else:
        fields["From"] = FROM
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ok = 200 <= int(getattr(resp, "status", 201)) < 300
            print(f"[SMS {'sent' if ok else 'unexpected'}] to={to[-4:]}", flush=True)
            return ok
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
        except Exception:
            detail = str(exc)
        print(f"[SMS Twilio HTTP {exc.code}] {detail}", flush=True)
        return False
    except Exception as exc:
        print(f"[SMS error] {type(exc).__name__}: {exc}", flush=True)
        return False


# All existing 2.0 code calls core.send_sms dynamically, so replacing it here fixes
# verification, opening offers, and artist alerts without importing legacy modules.
core.send_sms = send_sms
core.TWILIO_SID = SID
core.TWILIO_TOKEN = TOKEN
core.TWILIO_FROM = FROM
