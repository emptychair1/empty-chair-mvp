"""Public-web discovery feeder for Hunter Watchtower.

Goal: add up to 100 NEW, pain-qualified tattoo targets per UTC day.
Uses the MIT-licensed DDGS metasearch client; Watchtower remains the authenticated
observer after discovery.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from ddgs import DDGS
from hunter import watchtower_persistence as durable

DAILY_QUOTA=100
CITIES=("Atlanta GA","Nashville TN","Austin TX","Dallas TX","Houston TX","Denver CO","Portland OR","Seattle WA","Los Angeles CA","San Diego CA","Phoenix AZ","Chicago IL","New York NY","Philadelphia PA","Charlotte NC","Raleigh NC","Orlando FL","Tampa FL","Miami FL","Columbus OH","Detroit MI","Minneapolis MN","Kansas City MO","St Louis MO","Boston MA","Baltimore MD","Washington DC","Pittsburgh PA","Cleveland OH","Cincinnati OH","Indianapolis IN","Louisville KY","Memphis TN","New Orleans LA","Birmingham AL","Savannah GA","Jacksonville FL","Fort Lauderdale FL","Salt Lake City UT","Las Vegas NV","Sacramento CA","San Jose CA","Oakland CA","Richmond VA","Virginia Beach VA","Charleston SC","Greenville SC","Oklahoma City OK","Tulsa OK","Omaha NE","Albuquerque NM")
PHRASES=('"last minute availability" tattoo Instagram','"cancellation spot" tattoo Instagram','"cancellations" tattoo "Instagram story"','"last minute opening" tattoo Instagram','"cancellation list" tattoo Instagram','"appointment opened up" tattoo Instagram','"reschedule" tattoo "Instagram story"','"client cancelled" tattoo Instagram','"client canceled" tattoo Instagram','"cancellation available" tattoo Instagram','"spot opened up" tattoo artist Instagram','"had a cancellation" tattoo Instagram','"last minute tattoo appointment" Instagram','"cancellation channel" tattoo Instagram','"availability channel" tattoo Instagram')
HANDLE_RE=re.compile(r"@([A-Za-z0-9._]{2,30})\b")
IG_RE=re.compile(r"instagram\.com/(?:_u/)?([A-Za-z0-9._]{2,30})(?:[/?#]|$)",re.I)
STOP={"instagram","tattoo","tattoos","tattooartist","explore","explorepage","gmail.com","yahoo.com","hotmail.com","reel","reels","p","stories","story","accounts"}
PAIN=("cancellation","cancelation","cancelled","canceled","last minute","last-minute","opening","opened up","reschedule","no-show","no show","availability")
NON_TARGET=("expo","convention","tattoo show","tattooshow","magazine","media","awards","supply","supplies","school","academy","conference","festival","guest spot directory")
TARGET_CONTEXT=("tattoo artist","tattooer","tattooist","tattoo studio","tattoo shop","tattoos by","tattooing","booking","appointment")

def _existing()->set[str]:
    with durable.connection() as c:
        rows=c.execute(f"SELECT username FROM {durable.SCHEMA}.targets").fetchall()
    return {str(r['username']).lower() for r in rows}

def discovered_today_count()->int:
    with durable.connection() as c:
        row=c.execute(f"SELECT COUNT(*) n FROM {durable.SCHEMA}.targets WHERE created_at >= date_trunc('day',NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AND source LIKE 'discovery:%'").fetchone()
    return int(row['n'])

def _text(result:dict[str,Any])->str:
    return " ".join(str(result.get(k) or "") for k in ("title","body","href","url"))

def _instagram_url_handle(result:dict[str,Any])->str|None:
    for key in ("href","url"):
        raw=str(result.get(key) or "")
        m=IG_RE.search(raw)
        if m:return m.group(1).lower().rstrip('.')
    return None

def _handles(result:dict[str,Any])->list[str]:
    text=_text(result)
    primary=_instagram_url_handle(result)
    found=[]
    if primary:found.append(primary)
    # Only accept snippet @mentions when there is no direct Instagram account URL.
    # This prevents captions tagging unrelated accounts from poisoning the roster.
    if not primary:
        found.extend(m.group(1).lower().rstrip('.') for m in HANDLE_RE.finditer(text))
    out=[]
    for h in found:
        if h in STOP or not 2<=len(h)<=30 or h.startswith('.') or h in out:continue
        if any(token in h for token in ("expo","convention","tattooshow","tattoo_show","magazine","supply")):continue
        out.append(h)
    return out

def _score(result:dict[str,Any])->tuple[int,str]|None:
    text=_text(result).lower()
    if "tattoo" not in text or not any(p in text for p in PAIN):return None
    if any(x in text for x in NON_TARGET):return None
    # Require language suggesting a bookable artist/studio, unless the result URL itself
    # is an Instagram account and the snippet has strong cancellation language.
    strong_cancel=any(x in text for x in ("cancellation","cancelation","cancelled","canceled","last minute","last-minute"))
    if not any(x in text for x in TARGET_CONTEXT) and not (_instagram_url_handle(result) and strong_cancel):return None
    if "broadcast channel" in text and ("cancel" in text or "opening" in text):return 100,"broadcast"
    if any(x in text for x in ("cancellation","cancelation","cancelled","canceled")):return 95,"cancellation"
    if "last minute" in text or "last-minute" in text:return 90,"last_minute"
    return 85,"opening"

def discover_daily(quota:int=DAILY_QUOTA)->dict[str,Any]:
    if not durable.enabled():return {"ok":False,"reason":"durable persistence disabled","added":0}
    today=discovered_today_count();need=max(0,min(int(quota),DAILY_QUOTA)-today)
    if not need:return {"ok":True,"quota":DAILY_QUOTA,"today":today,"added":0,"remaining":0}
    existing=_existing();added=[];queries=0;errors=[]
    searcher=DDGS(timeout=10)
    day=datetime.now(timezone.utc).timetuple().tm_yday
    # Large deterministic daily surface: 15 pain phrases x 8 rotating US markets.
    combos=[(p,CITIES[(i*11+day+j*7)%len(CITIES)]) for i,p in enumerate(PHRASES) for j in range(8)]
    for phrase,city in combos:
        if len(added)>=need:break
        q=f"{phrase} {city}";queries+=1
        try:results=searcher.text(q,region="us-en",safesearch="moderate",max_results=40,backend="auto") or []
        except Exception as exc:
            errors.append(f"{exc.__class__.__name__}:{str(exc)[:120]}");continue
        for result in results:
            scored=_score(result)
            if not scored:continue
            priority,signal=scored
            for handle in _handles(result):
                if handle in existing:continue
                durable.upsert_target(handle,interval_minutes=60,priority=priority,source=f"discovery:web:{signal}",enabled=True)
                existing.add(handle);added.append(handle)
                if len(added)>=need:break
            if len(added)>=need:break
    total=discovered_today_count()
    return {"ok":True,"quota":DAILY_QUOTA,"today":total,"added":len(added),"remaining":max(0,DAILY_QUOTA-total),"queries":queries,"errors":errors[-3:]}
