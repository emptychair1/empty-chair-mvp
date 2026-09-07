"""Render Hunter inside the shared Empty Chair 2.0 amber CRT shell."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse

import v2_app as core
import v2_hunter_operator as hunter


# Hunter originally shipped with a standalone dark-card document. Replace only its GET
# screen so it inherits the exact same Empty Chair header, amber palette, scanlines,
# typography, settings gear, spacing, and controls as the rest of the v2 product.
for route in list(core.app.router.routes):
    if getattr(route, "path", None) == "/owner/hunter" and "GET" in (getattr(route, "methods", set()) or set()):
        core.app.router.routes.remove(route)


HUNTER_CSS = """
<style>
.hunter-head { display:flex; align-items:flex-end; justify-content:space-between; gap:18px; margin-bottom:22px; }
.hunter-head h1 { margin:0; }
.hunter-waiting { text-align:right; color:var(--dim); font-size:11px; }
.hunter-waiting b { display:block; color:var(--bright); font-size:28px; font-weight:400; line-height:1; }
.hunter-metrics { margin:18px 0 30px; }
.hunter-metrics .status span:last-child { color:var(--bright); }
.hunter-target { border-top:1px solid var(--off); border-bottom:1px solid var(--off); padding:24px 0 22px; margin-top:10px; }
.hunter-eyebrow { color:var(--amber); font-size:11px; letter-spacing:.14em; margin-bottom:12px; }
.hunter-name { color:var(--dim); font-size:12px; margin-bottom:5px; }
.hunter-target h1 { color:var(--bright); font-size:28px; margin:0 0 8px; overflow-wrap:anywhere; }
.hunter-context { color:var(--dim); font-size:12px; line-height:1.5; margin:0 0 22px; }
.hunter-open { margin-bottom:10px; }
.hunter-actions { display:grid; grid-template-columns:2fr 1fr; gap:10px; }
.hunter-actions form { margin:0; }
.hunter-actions button { height:100%; }
.hunter-handled { background:var(--off); color:var(--bright); }
.hunter-skip { border-color:var(--off); color:var(--amber); }
.hunter-hint { color:var(--dim); font-size:10px; line-height:1.55; text-align:center; margin:15px 4px 0; }
.hunter-empty { text-align:center; border-top:1px solid var(--off); border-bottom:1px solid var(--off); padding:42px 10px; }
.hunter-empty .big { margin-bottom:10px; }
@media (max-width:360px) { .hunter-actions { grid-template-columns:1fr; } }
</style>
"""


@core.app.get("/owner/hunter", response_class=HTMLResponse)
def operator_console_crt(request: Request):
    hunter.admin_artist(request)
    db = core.DB()
    try:
        hunter.ensure_tables(db)
        pending_rows = [dict(r) for r in db.execute(
            """SELECT * FROM hunter_operator_targets
               WHERE decision='PENDING' AND username IS NOT NULL AND profile_url IS NOT NULL
               ORDER BY first_ingested_at ASC, score DESC, username ASC"""
        ).fetchall()]
        today = hunter._today_prefix()
        new_today = int(db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE first_ingested_at LIKE ?", (today + "%",)
        ).fetchone()["n"])
        handled_today = int(db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='HANDLED' AND decided_at LIKE ?", (today + "%",)
        ).fetchone()["n"])
        skipped_today = int(db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='SKIPPED' AND decided_at LIKE ?", (today + "%",)
        ).fetchone()["n"])
    finally:
        db.close()

    followers = hunter._instagram_followers()
    website_visits = hunter._website_visits()
    follower_display = f"{followers:,}" if followers is not None else "—"
    remaining = len(pending_rows)
    current = hunter._display_target(pending_rows[0]) if pending_rows else None

    metrics = f"""
    <div class='hunter-metrics'>
      <div class='status'><span>NEW TODAY</span><span>{new_today:,}</span></div>
      <div class='status'><span>HANDLED</span><span>{handled_today:,}</span></div>
      <div class='status'><span>SKIPPED</span><span>{skipped_today:,}</span></div>
      <div class='status'><span>FOLLOWERS</span><span>{follower_display}</span></div>
      <div class='status'><span>WEBSITE VISITS</span><span>{website_visits:,}</span></div>
    </div>
    """

    if current:
        account_id = str(current.get("account_id") or "")
        username_raw = str(current.get("username") or "").strip().lstrip("@")
        username = hunter.esc(username_raw)
        name = hunter.esc(current.get("name") or "")
        market = hunter.esc(current.get("market") or "")
        source = hunter.esc(current.get("activity_source") or "")
        instagram_profile = f"https://www.instagram.com/_u/{quote(username_raw, safe='._')}/"
        path_id = quote(account_id, safe="")
        identity = f"<div class='hunter-name'>{name}</div>" if name and name.lower() != username.lower() else ""
        context = " // ".join(bit for bit in (market, source) if bit)
        target = f"""
        <section class='hunter-target'>
          <div class='hunter-eyebrow'>&gt;&gt; NEXT ARTIST</div>
          {identity}
          <h1>@{username}</h1>
          <p class='hunter-context'>{context or 'FRESH TATTOO ARTIST'}</p>
          <a class='button hunter-open' href='{hunter.esc(instagram_profile)}'>OPEN INSTAGRAM</a>
          <div class='hunter-actions'>
            <form method='post' action='/owner/hunter/{path_id}/decision'>
              <input type='hidden' name='decision' value='HANDLED'>
              <button class='hunter-handled'>HANDLED</button>
            </form>
            <form method='post' action='/owner/hunter/{path_id}/decision'>
              <input type='hidden' name='decision' value='SKIPPED'>
              <button class='hunter-skip'>SKIP</button>
            </form>
          </div>
          <p class='hunter-hint'>OPEN PROFILE // FOLLOW OR REVIEW MANUALLY // MARK HANDLED</p>
        </section>
        """
    else:
        target = """
        <section class='hunter-empty success'>
          <div class='big'>[✓]</div>
          <h1>YOU'RE CAUGHT UP</h1>
          <p class='dim'>Hunter has no new artists waiting right now.</p>
        </section>
        """

    body = f"""
    <div class='hunter-head'>
      <div><p class='dim' style='margin:0 0 6px'>FOUNDER // ACQUISITION</p><h1>HUNTER</h1></div>
      <div class='hunter-waiting'><b>{remaining:,}</b>WAITING</div>
    </div>
    {metrics}
    {target}
    """
    return core.page("Hunter", body, head=HUNTER_CSS)


print("Hunter CRT UI loaded // shared Empty Chair shell", flush=True)
