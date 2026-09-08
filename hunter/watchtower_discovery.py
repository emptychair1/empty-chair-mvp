"""Public-web discovery feeder for Hunter Watchtower.

Goal: add up to 100 NEW, pain-qualified tattoo targets per UTC day.
Uses the MIT-licensed DDGS metasearch client; Watchtower remains the authenticated
observer after discovery.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Any
from ddgs import DDGS
from hunter import watchtower_persistence as durable

DAILY_QUOTA=100
CITIES=("Atlanta GA","Nashville TN","Austin TX","Dallas TX","Houston TX","Denver CO","Portland OR","Seattle WA","Los Angeles CA","San Diego CA","Phoenix AZ","Chicago IL","New York NY","Philadelphia PA","Charlotte NC","Raleigh NC","Orlando FL","Tampa FL","Miami FL","Columbus OH","Detroit MI","Minneapolis MN","Kansas City MO","St Louis MO")
PHRASES=('"last minute availability" tattoo Instagram','"cancellation spot" tattoo Instagram','"cancellations" tattoo "Instagram story"','"last minute opening" tattoo "Instagram"','"cancellation list" tattoo Instagram','"appointment opened up" tattoo Instagram','"reschedule" tattoo "Instagram story"')
HANDLE_RE=re.compile(r"@([A-Za-z0-9._]{2,30})\b")
IG_RE=re.compile(r"instagram\.com/(?:_u/)?([A-Za-z0-9._]{2,30})(?:[/?#]|$)",re.I)
STOP={"instagram","tattoo","tattoos","tattooartist","explore","explorepage","gmail.com","yahoo.com","hotmail.com"}
PAIN=("cancellation","cancelation","cancelled","canceled","last minute","last-minute","opening","opened up","reschedule","no-show","no show","availability")

def _existing()->set[str]:
    with durable.connection() as c:
        rows=c.execute(f"SELECT username FROM {durable.SCHEMA}.targets").fetchall()
    return {str(r['username']).lower() for r in rows}

def discovered_today_count()->int:
    with durable.connection() as c:
        row=c.execute(f"SELECT COUNT(*) n FROM {durable.SCHEMA}.targets WHERE created_at >= date_trunc('day',NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AND source LIKE 'discovery:%'").fetchone()
    return int(row['n'])

def _handles(result:dict[str,Any])->set[str]:
    text=" ".join(str(result.get(k) or "") for k in ("title","body","href","url"))
    found={m.group(1).lower().rstrip('.') for m in HANDLE_RE.finditer(text)}
    found|={m.group(1).lower().rstrip('.') for m in IG_RE.finditer(text)}
    return {h for h in found if h not in STOP and 2<=len(h)<=30 and not h.startswith('.')}

def _score(result:dict[str,Any])->tuple[int,str]|None:
    text=" ".join(str(result.get(k) or "") for k in ("title","body","href","url")).lower()
    if "tattoo" not in text or not any(p in text for p in PAIN):return None
    if "broadcast channel" in text and ("cancel" in text or "opening" in text):return 100,"broadcast"
    if "cancellation" in text or "cancelation" in text or "cancelled" in text or "canceled" in text:return 95,"cancellation"
    if "last minute" in text or "last-minute" in text:return 90,"last_minute"
    return 85,"opening"

def discover_daily(quota:int=DAILY_QUOTA)->dict[str,Any]:
    if not durable.enabled():return {"ok":False,"reason":"durable persistence disabled","added":0}
    today=discovered_today_count();need=max(0,min(int(quota),DAILY_QUOTA)-today)
    if not need:return {"ok":True,"quota":DAILY_QUOTA,"today":today,"added":0,"remaining":0}
    existing=_existing();added=[];queries=0;errors=[]
    searcher=DDGS(timeout=10)
    # Rotate phrase/city combinations by UTC day so discovery surface changes daily.
    day=datetime.now(timezone.utc).timetuple().tm_yday
    combos=[(p,CITIES[(i+day)%len(CITIES)]) for i,p in enumerate(PHRASES) for _ in (0,1,2,3)]
    combos=[(p,CITIES[(i*7+day+j)%len(CITIES)]) for i,p in enumerate(PHRASES) for j in range(4)]
    for phrase,city in combos:
        if len(added)>=need:break
        q=f"{phrase} {city}";queries+=1
        try:results=searcher.text(q,region="us-en",safesearch="moderate",max_results=30,backend="auto") or []
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
