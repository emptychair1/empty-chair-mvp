"""Render Watchtower-enriched Hunter leads inside the Empty Chair CRT shell."""
from __future__ import annotations
import json,os
from datetime import datetime,timezone
from html import escape
from urllib.error import HTTPError,URLError
from urllib.parse import quote
from urllib.request import Request as URLRequest,urlopen
from fastapi import Request
from fastapi.responses import HTMLResponse
import v2_app as core
import v2_hunter_operator as hunter

for route in list(core.app.router.routes):
    if getattr(route,"path",None)=="/owner/hunter" and "GET" in (getattr(route,"methods",set()) or set()):core.app.router.routes.remove(route)
WATCHTOWER_URL=os.getenv("WATCHTOWER_URL","https://empty-chair-hunter-watchtower.onrender.com").rstrip("/")

def _token(): return (os.getenv("HUNTER_WATCHTOWER_BRIDGE_TOKEN") or os.getenv("WATCHTOWER_API_TOKEN") or "").strip()
HUNTER_CSS="""<style>.hunter-head{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:18px}.hunter-head h1{margin:0}.hunter-live{text-align:right;color:var(--dim);font-size:10px}.hunter-live b{display:block;color:var(--bright);font-size:25px;font-weight:400}.hunter-metrics{margin:16px 0 20px}.hunter-metrics .status span:last-child{color:var(--bright)}.hunter-filters{display:flex;gap:8px;overflow:auto;padding-bottom:14px}.hunter-filter{border:1px solid var(--off);border-radius:999px;padding:8px 12px;color:var(--dim);font-size:10px;text-decoration:none;white-space:nowrap}.hunter-filter.active{border-color:var(--amber);color:var(--bright)}.hunter-list{display:grid;gap:10px}.hunter-lead{border:1px solid var(--off);border-radius:15px;background:rgba(11,9,5,.94);overflow:hidden}.hunter-lead summary{list-style:none;cursor:pointer;padding:16px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px}.hunter-user{color:var(--bright);font-size:17px;overflow-wrap:anywhere}.hunter-sub{color:var(--dim);font-size:9px;margin-top:5px}.hunter-score{text-align:right}.hunter-score b{display:block;font-size:24px;font-weight:400;color:var(--bright)}.hunter-tier{font-size:9px}.hunter-detail{border-top:1px solid var(--off);padding:14px 16px}.hunter-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.hunter-stat{border:1px solid rgba(255,176,0,.14);border-radius:10px;padding:10px}.hunter-stat span{display:block;color:var(--dim);font-size:8px}.hunter-stat b{color:var(--bright);font-size:13px;font-weight:400}.hunter-actions{margin-top:12px}.hunter-actions a{text-decoration:none}.hunter-empty,.hunter-error{border:1px solid var(--off);border-radius:14px;padding:28px 16px;text-align:center}.hunter-error p,.hunter-empty p{color:var(--dim);font-size:11px}</style>"""
def _watchtower(path,timeout=12.0):
    token=_token()
    if not token:raise RuntimeError("Hunter Watchtower bridge credential is not configured")
    req=URLRequest(f"{WATCHTOWER_URL}{path}",headers={"Authorization":f"Bearer {token}","Accept":"application/json"},method="GET")
    try:
        with urlopen(req,timeout=timeout) as response:payload=json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:raise RuntimeError(f"Watchtower returned HTTP {exc.code}") from exc
    except URLError as exc:raise RuntimeError(f"Watchtower unavailable: {exc.reason}") from exc
    if not isinstance(payload,dict):raise RuntimeError("Watchtower returned an invalid response")
    return payload
def _fmt_time(value):
    if not value:return "NOT OBSERVED"
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"));dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc);age=max(0,int((datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()))
        return f"{max(1,age//60)}M AGO" if age<3600 else f"{age//3600}H AGO" if age<86400 else f"{age//86400}D AGO"
    except Exception:return escape(str(value))
def _lead_card(lead):
    raw=str(lead.get("username") or "").strip().lstrip("@");username=escape(raw);tier=str(lead.get("tier") or "WATCH").upper();tier=tier if tier in {"HOT","WARM","WATCH"} else "WATCH";score=int(lead.get("hunter_score") or 0);obs=int(lead.get("observations") or 0);hits=int(lead.get("recovery_hits") or 0);peak=int(lead.get("peak_intent") or 0);source=escape(str(lead.get("source") or "UNKNOWN").replace("discovery:web:","WEB // ").replace("_"," ").upper());last=_fmt_time(lead.get("last_observed_at"));pain=_fmt_time(lead.get("last_recovery_at")) if lead.get("last_recovery_at") else "NONE YET";url=f"https://www.instagram.com/{quote(raw,safe='._')}/"
    return f"<details class='hunter-lead'><summary><div><div class='hunter-user'>@{username}</div><div class='hunter-sub'>{source} // LAST SEEN {last}</div></div><div class='hunter-score'><b>{score}</b><span class='hunter-tier'>{tier}</span></div></summary><div class='hunter-detail'><div class='hunter-grid'><div class='hunter-stat'><span>OBSERVATIONS</span><b>{obs}</b></div><div class='hunter-stat'><span>RECOVERY HITS</span><b>{hits}</b></div><div class='hunter-stat'><span>PEAK INTENT</span><b>{peak}</b></div><div class='hunter-stat'><span>LAST PAIN SIGNAL</span><b>{pain}</b></div></div><div class='hunter-actions'><a class='button' href='{escape(url)}' target='_blank' rel='noopener'>OPEN INSTAGRAM ↗</a></div></div></details>"
@core.app.get("/owner/hunter",response_class=HTMLResponse)
def hunter_command_center(request:Request):
    hunter.admin_artist(request);selected=str(request.query_params.get("tier") or "ALL").upper();selected=selected if selected in {"ALL","HOT","WARM","WATCH"} else "ALL";error=None;leads=[];jobs={}
    try:
        leads=[x for x in (_watchtower("/v1/leads?limit=500").get("leads") or []) if isinstance(x,dict)];jobs=_watchtower("/v1/status").get("jobs") or {}
    except Exception as exc:error=str(exc)
    counts={"HOT":0,"WARM":0,"WATCH":0}
    for lead in leads:
        tier=str(lead.get("tier") or "WATCH").upper()
        if tier in counts:counts[tier]+=1
    enriched=sum(1 for x in leads if int(x.get("observations") or 0)>0);visible=leads if selected=="ALL" else [x for x in leads if str(x.get("tier") or "WATCH").upper()==selected]
    metrics="<div class='hunter-metrics'>"+"".join(f"<div class='status'><span>{k}</span><span>{v:,}</span></div>" for k,v in [("ENRICHED",enriched),("HOT",counts['HOT']),("WARM",counts['WARM']),("WATCH",counts['WATCH']),("OBSERVATIONS",int(jobs.get('finished') or 0))])+"</div>"
    filters="<div class='hunter-filters'>"+"".join(f"<a class='hunter-filter {'active' if selected==t else ''}' href='/owner/hunter?tier={t}'>{t} {len(leads) if t=='ALL' else counts.get(t,0)}</a>" for t in ("ALL","HOT","WARM","WATCH"))+"</div>"
    content=f"<section class='hunter-error'><h2>WATCHTOWER LINK OFFLINE</h2><p>{escape(error)}</p></section>" if error else "<section class='hunter-empty'><h2>NO LEADS IN THIS TIER</h2><p>Watchtower is discovering and enriching the bucket.</p></section>" if not visible else "<div class='hunter-list'>"+"".join(_lead_card(x) for x in visible)+"</div>"
    body=f"<div class='hunter-head'><div><p class='dim'>WATCHTOWER // PROSPECT INTELLIGENCE</p><h1>HUNTER</h1></div><div class='hunter-live'><b>{len(leads):,}</b>IN BUCKET</div></div>{metrics}{filters}{content}"
    return core.page("Hunter",body,head=HUNTER_CSS)
print("Hunter CRT UI loaded // Watchtower lead command center",flush=True)
