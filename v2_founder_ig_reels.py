"""Founder-only Instagram Reels preview page for Empty Chair scenario content."""
from __future__ import annotations

import os

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

import v2_app as core
import v2_settings as settings
from hunter.operator_auth import is_admin_identity, parse_phones

ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("EMPTY_CHAIR_ADMIN_EMAILS", "").split(",")
    if e.strip()
}
ADMIN_PHONES = parse_phones(os.getenv("EMPTY_CHAIR_ADMIN_PHONES", ""))


def _founder(request: Request):
    artist = core.current_artist(request)
    if not artist or not is_admin_identity(
        artist,
        admin_emails=ADMIN_EMAILS,
        admin_phones=ADMIN_PHONES,
    ):
        raise HTTPException(404, "Not found")
    return artist


REELS_CSS = """
<style>
.reels-wrap{max-width:760px;margin:0 auto}
.reels-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:20px}
.reels-head h1{margin:0}.reels-badge{font-size:11px;color:var(--dim);text-align:right}
.reel-phone{border:1px solid var(--off);border-radius:28px;padding:14px;background:#080703;box-shadow:0 0 34px rgba(255,176,0,.08)}
.reel-screen{border:1px solid rgba(255,176,0,.16);border-radius:20px;overflow:hidden;background:#0b0905}
.reel-top{display:flex;justify-content:space-between;padding:12px 15px;border-bottom:1px solid rgba(255,176,0,.12);font-size:11px;color:var(--dim)}
.scene{padding:18px 16px;border-bottom:1px solid rgba(255,176,0,.12)}
.scene:last-child{border-bottom:0}.scene-n{font-size:10px;color:var(--dim);letter-spacing:.16em;margin-bottom:8px}.scene h2{margin:0 0 9px;font-size:22px;color:var(--bright)}
.scene p{margin:0;color:var(--dim);font-size:12px;line-height:1.55}.danger{border:1px solid rgba(255,92,52,.65);padding:14px;border-radius:12px}.danger h2{color:#ff6a45}
.status-card{border:1px solid var(--off);border-radius:12px;padding:14px;margin-top:10px}.row{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid rgba(255,176,0,.12)}.row:first-child{border-top:0}.row strong{color:var(--bright)}
.sms{display:flex;flex-direction:column;gap:10px;margin-top:12px}.bubble{max-width:82%;padding:11px 12px;border:1px solid rgba(255,176,0,.28);border-radius:12px;font-size:12px;line-height:1.45}.bubble.out{align-self:flex-start}.bubble.in{align-self:flex-end;color:var(--bright);border-color:var(--off)}
.money{font-size:34px;color:var(--bright);letter-spacing:.04em;margin-top:8px}.cta{display:block;text-align:center;border:1px solid var(--off);border-radius:12px;padding:15px;margin-top:16px;color:var(--bright);font-size:18px;text-decoration:none}.tiny{text-align:center;color:var(--dim);font-size:10px;margin-top:8px}.caption{margin-top:18px;padding:16px;border:1px solid rgba(255,176,0,.15);border-radius:14px}.caption h3{margin:0 0 8px;color:var(--bright);font-size:13px}.caption p{margin:0;color:var(--dim);font-size:12px;line-height:1.6}
</style>
"""


@core.app.get("/owner/ig-reels", response_class=HTMLResponse)
def founder_ig_reels(request: Request):
    _founder(request)
    body = """
    <div class='reels-wrap'>
      <div class='reels-head'>
        <div><p class='dim' style='margin:0 0 5px'>FOUNDER // CONTENT</p><h1>IG REELS</h1></div>
        <div class='reels-badge'>SCENARIO 01<br>RECOVERY + DEPOSIT</div>
      </div>

      <div class='reel-phone'>
        <div class='reel-screen'>
          <div class='reel-top'><span>EMPTY CHAIR</span><span>9:41</span></div>

          <section class='scene'>
            <div class='scene-n'>01 // CANCELLATION</div>
            <div class='danger'>
              <h2>TUE 3:00 PM // APPOINTMENT CANCELLED</h2>
              <p>Client cancelled 2 hours before the appointment. This spot is now open.</p>
            </div>
          </section>

          <section class='scene'>
            <div class='scene-n'>02 // RECOVERY</div>
            <h2>RECOVERY STARTED</h2>
            <p>&gt; CHECKING AVAILABILITY<br>&gt; FILTERING CLIENTS<br>&gt; RANKING BY FIT<br>&gt; PREPARING OUTREACH</p>
          </section>

          <section class='scene'>
            <div class='scene-n'>03 // TOP MATCHES</div>
            <div class='status-card'>
              <div class='row'><strong>01 // MAYA</strong><span>92% MATCH</span></div>
              <div class='row'><span>02 // JORDAN</span><span>87% MATCH</span></div>
              <div class='row'><span>03 // ALEX</span><span>79% MATCH</span></div>
            </div>
          </section>

          <section class='scene'>
            <div class='scene-n'>04 // SMS</div>
            <h2>OUTREACH</h2>
            <div class='sms'>
              <div class='bubble out'>Opening today at 3:00 PM. Want it?</div>
              <div class='bubble in'>YES — I CAN TAKE IT ✓</div>
            </div>
          </section>

          <section class='scene'>
            <div class='scene-n'>05 // PAYMENT</div>
            <h2>DEPOSIT RECEIVED</h2>
            <div class='money'>$80 PAID</div>
            <p>DEPOSIT CONFIRMED // TUE 3:00 PM</p>
          </section>

          <section class='scene'>
            <div class='scene-n'>06 // FILLED</div>
            <h2>CHAIR FILLED ✓</h2>
            <div class='status-card'>
              <div class='row'><strong>SLOT RECOVERED</strong><span>CLIENT CONFIRMED</span></div>
              <div class='row'><span>REVENUE PROTECTED</span><span>BUSINESS KEEPS MOVING</span></div>
            </div>
            <p style='margin-top:14px;text-align:center'>ONE RECOVERED SPOT CAN PAY FOR EMPTY CHAIR.</p>
            <a class='cta' href='/'>7-DAY FREE TRIAL →</a>
            <div class='tiny'>NO CARD REQUIRED</div>
          </section>
        </div>
      </div>

      <div class='caption'>
        <h3>CAPTION</h3>
        <p>What a recovered cancellation can look like inside Empty Chair. A last-minute opening gets matched, claimed, and secured with a deposit — without adding another workflow to your day.</p>
      </div>
    </div>
    """
    return core.page("IG Reels", body, head=REELS_CSS)


# Patch the founder settings page after v2_settings has registered it. This keeps
# the normal settings UI untouched for customers and only inserts the founder Reel link.
_original_settings_home = settings.settings_home
for route in list(core.app.router.routes):
    if getattr(route, "path", None) == "/settings" and "GET" in (getattr(route, "methods", set()) or set()):
        core.app.router.routes.remove(route)


@core.app.get("/settings", response_class=HTMLResponse)
def settings_home_with_reels(request: Request):
    response = _original_settings_home(request)
    artist = core.current_artist(request)
    if not artist or not is_admin_identity(
        artist,
        admin_emails=ADMIN_EMAILS,
        admin_phones=ADMIN_PHONES,
    ):
        return response
    body = response.body.decode("utf-8")
    reel_row = (
        '<a class="settings-row" href="/owner/ig-reels">'
        '<span>IG REELS<small>scenario previews // reels content</small></span>'
        '<span>›</span></a>'
    )
    marker = '<a class="settings-row" href="/owner/hunter">'
    if reel_row not in body:
        if marker in body:
            body = body.replace(marker, reel_row + marker, 1)
        else:
            body = body.replace('<div class="settings-list">', '<div class="settings-list">' + reel_row, 1)
    return HTMLResponse(content=body, status_code=response.status_code, headers=dict(response.headers))


print("Founder IG Reels preview loaded // scenario 01 // settings nav enabled", flush=True)
