"""Render Watchtower-enriched Hunter leads inside the Empty Chair CRT shell."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from html import escape
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as URLRequest, urlopen

from fastapi import Request
from fastapi.responses import HTMLResponse

import v2_app as core
import v2_hunter_operator as hunter


for route in list(core.app.router.routes):
    if getattr(route, "path", None) == "/owner/hunter" and "GET" in (getattr(route, "methods", set()) or set()):
        core.app.router.routes.remove(route)


WATCHTOWER_URL = os.getenv("WATCHTOWER_URL", "https://empty-chair-hunter-watchtower.onrender.com").rstrip("/")
WATCHTOWER_TOKEN = os.getenv("WATCHTOWER_API_TOKEN", "").strip()

HUNTER_CSS = """
<style>
.hunter-head{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:18px}.hunter-head h1{margin:0}.hunter-live{text-align:right;color:var(--dim);font-size:10px}.hunter-live b{display:block;color:var(--bright);font-size:25px;font-weight:400;line-height:1.05}.hunter-metrics{margin:16px 0 20px}.hunter-metrics .status span:last-child{color:var(--bright)}
.hunter-filters{display:flex;gap:8px;overflow:auto;padding:0 0 14px;scrollbar-width:none}.hunter-filters::-webkit-scrollbar{display:none}.hunter-filter{border:1px solid var(--off);border-radius:999px;padding:8px 12px;color:var(--dim);font-size:10px;letter-spacing:.08em;text-decoration:none;white-space:nowrap}.hunter-filter.active{border-color:var(--amber);color:var(--bright);box-shadow:0 0 16px rgba(255,176,0,.09)}
.hunter-list{display:grid;gap:10px}.hunter-lead{border:1px solid var(--off);border-radius:15px;background:rgba(11,9,5,.94);overflow:hidden}.hunter-lead summary{list-style:none;cursor:pointer;padding:16px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center}.hunter-lead summary::-webkit-details-marker{display:none}.hunter-identity{min-width:0}.hunter-user{color:var(--bright);font-size:17px;overflow-wrap:anywhere}.hunter-sub{color:var(--dim);font-size:9px;line-height:1.45;margin-top:5px;text-transform:uppercase}.hunter-score{text-align:right}.hunter-score b{display:block;font-size:24px;font-weight:400;color:var(--bright)}.hunter-tier{font-size:9px;letter-spacing:.13em}.hunter-tier.hot{color:#ff875f}.hunter-tier.warm{color:var(--amber)}.hunter-tier.watch{color:var(--dim)}
.hunter-detail{border-top:1px solid var(--off);padding:14px 16px 16px}.hunter-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.hunter-stat{border:1px solid rgba(255,176,0,.14);border-radius:10px;padding:10px}.hunter-stat span{display:block;color:var(--dim);font-size:8px;letter-spacing:.08em;margin-bottom:5px}.hunter-stat b{color:var(--bright);font-size:13px;font-weight:400;overflow-wrap:anywhere}.hunter-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}.hunter-actions a{text-align:center;text-decoration:none}.hunter-empty,.hunter-error{border:1px solid var(--off);border-radius:14px;padding:28px 16px;text-align:center}.hunter-error{border-color:rgba(255,100,70,.35)}.hunter-error p,.hunter-empty p{color:var(--dim);font-size:11px;line-height:1.55}.hunter-error code{color:var(--bright)}
@media(max-width:430px){.hunter-head{align-items:flex-start}.hunter-grid{grid-template-columns:1fr 1fr}.hunter-actions{grid-template-columns:1fr}.hunter-live b{font-size:21px}}
</style>
"""


def _watchtower(path: str, timeout: float = 12.0) -> dict:
    if not WATCHTOWER_TOKEN:
        raise RuntimeError("WATCHTOWER_API_TOKEN is not configured on the Empty Chair app service")
    req = URLRequest(
        f"{WATCHTOWER_URL}{path}",
        headers={"Authorization": f"Bearer {WATCHTOWER_TOKEN}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Watchtower returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Watchtower unavailable: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Watchtower returned an invalid response")
    return payload


def _fmt_time(value) -> str:
    if not value:
        return "NOT OBSERVED"
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
        if age < 3600:
            return f"{max(1, age // 60)}M AGO"
        if age < 86400:
            return f"{age // 3600}H AGO"
        return f"{age // 86400}D AGO"
    except Exception:
        return escape(str(value))


def _lead_card(lead: dict) -> str:
    username_raw = str(lead.get("username") or "").strip().lstrip("@")
    username = escape(username_raw)
    tier_raw = str(lead.get("tier") or "WATCH").upper()
    tier = tier_raw if tier_raw in {"HOT", "WARM", "WATCH"} else "WATCH"
    score = int(lead.get("hunter_score") or 0)
    priority = int(lead.get("priority") or 0)
    observations = int(lead.get("observations") or 0)
    recovery_hits = int(lead.get("recovery_hits") or 0)
    peak_intent = int(lead.get("peak_intent") or 0)
    source = escape(str(lead.get("source") or "UNKNOWN").replace("discovery:web:", "WEB // ").replace("_", " ").upper())
    last_observed = _fmt_time(lead.get("last_observed_at"))
    last_recovery = _fmt_time(lead.get("last_recovery_at")) if lead.get("last_recovery_at") else "NONE YET"
    instagram_web = f"https://www.instagram.com/{quote(username_raw, safe='._')}/"
    return f"""
    <details class='hunter-lead' data-tier='{tier}'>
      <summary>
        <div class='hunter-identity'>
          <div class='hunter-user'>@{username}</div>
          <div class='hunter-sub'>{source} // LAST SEEN {last_observed}</div>
        </div>
        <div class='hunter-score'><b>{score}</b><span class='hunter-tier {tier.lower()}'>{tier}</span></div>
      </summary>
      <div class='hunter-detail'>
        <div class='hunter-grid'>
          <div class='hunter-stat'><span>OBSERVATIONS</span><b>{observations}</b></div>
          <div class='hunter-stat'><span>RECOVERY HITS</span><b>{recovery_hits}</b></div>
          <div class='hunter-stat'><span>PEAK INTENT</span><b>{peak_intent}</b></div>
          <div class='hunter-stat'><span>DISCOVERY PRIORITY</span><b>{priority}</b></div>
          <div class='hunter-stat'><span>LAST OBSERVED</span><b>{last_observed}</b></div>
          <div class='hunter-stat'><span>LAST PAIN SIGNAL</span><b>{last_recovery}</b></div>
        </div>
        <div class='hunter-actions'>
          <a class='button' href='{escape(instagram_web)}' target='_blank' rel='noopener'>OPEN INSTAGRAM ↗</a>
          <a class='button secondary' href='/owner/hunter?tier={tier}'>SHOW {tier}</a>
        </div>
      </div>
    </details>
    """


@core.app.get("/owner/hunter", response_class=HTMLResponse)
def hunter_command_center(request: Request):
    hunter.admin_artist(request)
    selected = str(request.query_params.get("tier") or "ALL").upper()
    if selected not in {"ALL", "HOT", "WARM", "WATCH"}:
        selected = "ALL"

    error = None
    leads: list[dict] = []
    jobs: dict = {}
    try:
        lead_payload = _watchtower("/v1/leads?limit=500")
        status_payload = _watchtower("/v1/status")
        leads = [x for x in (lead_payload.get("leads") or []) if isinstance(x, dict)]
        jobs = status_payload.get("jobs") or {}
    except Exception as exc:
        error = str(exc)

    counts = {"HOT": 0, "WARM": 0, "WATCH": 0}
    for lead in leads:
        tier = str(lead.get("tier") or "WATCH").upper()
        if tier in counts:
            counts[tier] += 1
    enriched = sum(1 for x in leads if int(x.get("observations") or 0) > 0)
    visible = leads if selected == "ALL" else [x for x in leads if str(x.get("tier") or "WATCH").upper() == selected]

    metrics = f"""
    <div class='hunter-metrics'>
      <div class='status'><span>ENRICHED</span><span>{enriched:,}</span></div>
      <div class='status'><span>HOT</span><span>{counts['HOT']:,}</span></div>
      <div class='status'><span>WARM</span><span>{counts['WARM']:,}</span></div>
      <div class='status'><span>WATCH</span><span>{counts['WATCH']:,}</span></div>
      <div class='status'><span>OBSERVATIONS</span><span>{int(jobs.get('finished') or 0):,}</span></div>
    </div>
    """
    filters = "<div class='hunter-filters'>" + "".join(
        f"<a class='hunter-filter {'active' if selected == tier else ''}' href='/owner/hunter?tier={tier}'>{tier} {len(leads) if tier == 'ALL' else counts.get(tier, 0)}</a>"
        for tier in ("ALL", "HOT", "WARM", "WATCH")
    ) + "</div>"

    if error:
        content = f"""
        <section class='hunter-error'>
          <h2>WATCHTOWER LINK OFFLINE</h2>
          <p>{escape(error)}</p>
          <p>The lead bucket is still safe in Watchtower; this screen needs the app-to-Watchtower server credential.</p>
        </section>
        """
    elif not visible:
        content = "<section class='hunter-empty'><h2>NO LEADS IN THIS TIER</h2><p>Watchtower is still discovering and enriching the bucket.</p></section>"
    else:
        content = "<div class='hunter-list'>" + "".join(_lead_card(x) for x in visible) + "</div>"

    body = f"""
    <div class='hunter-head'>
      <div><p class='dim' style='margin:0 0 6px'>WATCHTOWER // PROSPECT INTELLIGENCE</p><h1>HUNTER</h1></div>
      <div class='hunter-live'><b>{len(leads):,}</b>IN BUCKET</div>
    </div>
    {metrics}
    {filters}
    {content}
    """
    return core.page("Hunter", body, head=HUNTER_CSS)


print("Hunter CRT UI loaded // Watchtower lead command center", flush=True)
