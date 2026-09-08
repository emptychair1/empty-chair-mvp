"""Official Reddit OAuth retrieval for Founder Reddit Copilot.

Uses app-only OAuth when REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are set.
Falls back to the existing anonymous reader only when OAuth is not configured.
"""
from __future__ import annotations

import base64
import json
import os
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import v2_founder_reddit as reddit

CLIENT_ID=os.getenv("REDDIT_CLIENT_ID","").strip()
CLIENT_SECRET=os.getenv("REDDIT_CLIENT_SECRET","").strip()
USER_AGENT=os.getenv("REDDIT_USER_AGENT","EmptyChairFounderRadar/1.0 by EmptyChair").strip()
_TOKEN={"value":"","expires":0.0}


def _token() -> str:
    now=time.time()
    if _TOKEN["value"] and now < float(_TOKEN["expires"])-60:
        return str(_TOKEN["value"])
    auth=base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    body=urlencode({"grant_type":"client_credentials"}).encode()
    req=Request("https://www.reddit.com/api/v1/access_token",data=body,headers={
        "Authorization":f"Basic {auth}",
        "User-Agent":USER_AGENT,
        "Content-Type":"application/x-www-form-urlencoded",
        "Accept":"application/json",
    })
    with urlopen(req,timeout=8) as r:
        payload=json.loads(r.read().decode("utf-8"))
    value=str(payload.get("access_token") or "")
    if not value:
        raise RuntimeError("Reddit OAuth token missing")
    _TOKEN["value"]=value
    _TOKEN["expires"]=now+int(payload.get("expires_in") or 3600)
    return value


def _oauth_fetch(term:str) -> list[dict]:
    params=urlencode({"q":term,"restrict_sr":"1","sort":"new","t":"year","limit":"15","raw_json":"1"})
    req=Request(f"https://oauth.reddit.com/r/TattooArtists/search?{params}",headers={
        "Authorization":f"bearer {_token()}",
        "User-Agent":USER_AGENT,
        "Accept":"application/json",
    })
    with urlopen(req,timeout=8) as r:
        payload=json.loads(r.read().decode("utf-8"))
    return [x.get("data",{}) for x in payload.get("data",{}).get("children",[])]


_original_fetch=reddit._fetch


def _fetch(term:str) -> list[dict]:
    if CLIENT_ID and CLIENT_SECRET:
        try:
            rows=_oauth_fetch(term)
            if rows:
                return rows
        except Exception as exc:
            print(f"Founder Reddit OAuth fetch failed // {term}: {exc}",flush=True)
    return _original_fetch(term)


reddit._fetch=_fetch
reddit.REDDIT_RETRIEVAL_MODE="OAUTH" if CLIENT_ID and CLIENT_SECRET else "ANONYMOUS"
print(f"Founder Reddit retrieval loaded // {reddit.REDDIT_RETRIEVAL_MODE}",flush=True)
