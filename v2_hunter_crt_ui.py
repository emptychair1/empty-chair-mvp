"""Render Hunter inside the shared Empty Chair 2.0 amber CRT shell."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse

import v2_app as core
import v2_hunter_operator as hunter


for route in list(core.app.router.routes):
    if getattr(route, "path", None) == "/owner/hunter" and "GET" in (getattr(route, "methods", set()) or set()):
        core.app.router.routes.remove(route)


HUNTER_CSS = """
<style>
.hunter-head { display:flex; align-items:flex-end; justify-content:space-between; gap:18px; margin-bottom:22px; }
.hunter-head h1 { margin:0; }
.hunter-waiting { text-align:right; color:var(--dim); font-size:11px; }
.hunter-waiting b { display:block; color:var(--bright); font-size:28px; font-weight:400; line-height:1; }
.hunter-metrics { margin:18px 0 24px; }
.hunter-metrics .status span:last-child { color:var(--bright); }
.hunter-deck { position:relative; min-height:430px; overflow:hidden; touch-action:pan-y; }
.hunter-target { position:relative; border:1px solid var(--off); border-radius:18px; padding:28px 22px 22px; margin-top:8px; background:rgba(11,9,5,.95); box-shadow:0 0 30px rgba(255,176,0,.06); transform-origin:center 120%; will-change:transform,opacity; user-select:none; -webkit-user-select:none; touch-action:pan-y; }
.hunter-target.dragging { transition:none; }
.hunter-target.settling { transition:transform .18s ease, opacity .18s ease; }
.hunter-eyebrow { color:var(--amber); font-size:11px; letter-spacing:.14em; margin-bottom:16px; }
.hunter-name { color:var(--dim); font-size:12px; margin-bottom:6px; }
.hunter-target h1 { color:var(--bright); font-size:31px; margin:0 0 10px; overflow-wrap:anywhere; }
.hunter-context { color:var(--dim); font-size:12px; line-height:1.5; margin:0 0 26px; min-height:18px; }
.hunter-swipe-label { min-height:42px; display:flex; align-items:center; justify-content:center; text-align:center; color:var(--amber); font-size:13px; letter-spacing:.08em; margin:12px 0 20px; white-space:pre-line; }
.hunter-actions { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.hunter-actions button { height:100%; }
.hunter-follow { background:var(--off); color:var(--bright); }
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

    script = ""
    if current:
        account_id = str(current.get("account_id") or "")
        username_raw = str(current.get("username") or "").strip().lstrip("@")
        username = hunter.esc(username_raw)
        name = hunter.esc(current.get("name") or "")
        market = hunter.esc(current.get("market") or "")
        source = hunter.esc(current.get("activity_source") or "")
        instagram_web = f"https://www.instagram.com/_u/{quote(username_raw, safe='._')}/"
        instagram_native = f"instagram://user?username={quote(username_raw, safe='._')}"
        path_id = quote(account_id, safe="")
        identity = f"<div class='hunter-name'>{name}</div>" if name and name.lower() != username.lower() else ""
        context = " // ".join(bit for bit in (market, source) if bit)
        target = f"""
        <div class='hunter-deck'>
          <section class='hunter-target' id='hunter-card'
                   data-decision-url='/owner/hunter/{path_id}/decision'
                   data-instagram-native='{hunter.esc(instagram_native)}'
                   data-instagram-web='{hunter.esc(instagram_web)}'>
            <div class='hunter-eyebrow'>&gt;&gt; NEXT ARTIST</div>
            {identity}
            <h1>@{username}</h1>
            <p class='hunter-context'>{context or 'FRESH TATTOO ARTIST'}</p>
            <div class='hunter-swipe-label' id='hunter-swipe-label'>SWIPE RIGHT TO FOLLOW<br>SWIPE LEFT TO SKIP</div>
            <div class='hunter-actions'>
              <button type='button' class='hunter-skip' id='hunter-skip'>← SKIP</button>
              <button type='button' class='hunter-follow' id='hunter-follow'>FOLLOW →</button>
            </div>
            <p class='hunter-hint'>RIGHT OPENS INSTAGRAM // YOU TAP FOLLOW // LEFT SKIPS</p>
          </section>
        </div>
        """
        script = r"""
<script>
(() => {
  const card = document.getElementById('hunter-card');
  const label = document.getElementById('hunter-swipe-label');
  if (!card || !label) return;
  let startX = 0, startY = 0, dx = 0, active = false, committing = false;
  const threshold = 90;
  const idleLabel = 'SWIPE RIGHT TO FOLLOW\nSWIPE LEFT TO SKIP';

  function paint(x) {
    dx = x;
    const rotate = Math.max(-10, Math.min(10, x / 18));
    card.style.transform = `translateX(${x}px) rotate(${rotate}deg)`;
    if (x > 55) label.textContent = 'FOLLOW →';
    else if (x < -55) label.textContent = '← SKIP';
    else label.textContent = idleLabel;
  }

  function reset() {
    card.classList.remove('dragging');
    card.classList.add('settling');
    card.style.transform = 'translateX(0) rotate(0deg)';
    label.textContent = idleLabel;
    setTimeout(() => card.classList.remove('settling'), 190);
  }

  async function record(decision) {
    const form = new FormData();
    form.append('decision', decision);
    const response = await fetch(card.dataset.decisionUrl, {
      method: 'POST',
      body: form,
      credentials: 'same-origin',
      redirect: 'follow'
    });
    if (!response.ok) throw new Error(`Hunter decision failed: ${response.status}`);
  }

  function openInstagram() {
    const nativeUrl = card.dataset.instagramNative;
    const webUrl = card.dataset.instagramWeb;
    let hidden = false;
    const markHidden = () => { hidden = true; };
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) markHidden();
    }, { once: true });
    window.addEventListener('pagehide', markHidden, { once: true });
    window.location.assign(nativeUrl);
    setTimeout(() => {
      if (!hidden && document.visibilityState === 'visible') window.location.assign(webUrl);
    }, 850);
  }

  function commit(decision) {
    if (committing) return;
    committing = true;
    const follow = decision === 'HANDLED';
    card.classList.remove('dragging');
    card.classList.add('settling');
    card.style.transform = `translateX(${follow ? 560 : -560}px) rotate(${follow ? 14 : -14}deg)`;
    card.style.opacity = '0';

    if (follow) {
      record(decision).catch(() => {});
      openInstagram();
      return;
    }

    record(decision)
      .then(() => window.location.reload())
      .catch(() => {
        committing = false;
        card.style.opacity = '1';
        reset();
        label.textContent = 'TRY AGAIN';
      });
  }

  card.addEventListener('pointerdown', (e) => {
    if (committing) return;
    active = true;
    startX = e.clientX;
    startY = e.clientY;
    dx = 0;
    card.classList.add('dragging');
    try { card.setPointerCapture(e.pointerId); } catch (_) {}
  });

  card.addEventListener('pointermove', (e) => {
    if (!active || committing) return;
    const x = e.clientX - startX;
    const y = e.clientY - startY;
    if (Math.abs(y) > Math.abs(x) * 1.2) return;
    if (Math.abs(x) > 8) e.preventDefault();
    paint(x);
  }, { passive: false });

  card.addEventListener('pointerup', () => {
    if (!active || committing) return;
    active = false;
    if (dx > threshold) commit('HANDLED');
    else if (dx < -threshold) commit('SKIPPED');
    else reset();
  });

  card.addEventListener('pointercancel', () => {
    active = false;
    if (!committing) reset();
  });

  document.getElementById('hunter-follow').addEventListener('click', () => commit('HANDLED'));
  document.getElementById('hunter-skip').addEventListener('click', () => commit('SKIPPED'));
  window.addEventListener('pageshow', () => {
    if (committing) window.location.reload();
  });
})();
</script>
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
    return core.page("Hunter", body, script=script, head=HUNTER_CSS)


print("Hunter CRT UI loaded // web swipe cards", flush=True)
