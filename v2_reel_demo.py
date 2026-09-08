"""Full-screen in-app scenario screens for Empty Chair Reel creative.

These routes render a realistic simulated cancellation-recovery flow entirely inside the
real Empty Chair mobile UI. They are owner-preview content only; they do not write fake
customer/payment records or touch production recovery state.
"""
from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import v2_app as core


REEL_CSS = """
<style>
main { min-height:100svh; display:flex; flex-direction:column; padding-bottom:28px !important; }
header { margin-bottom:18px; }
.reel-screen { flex:1; display:flex; flex-direction:column; min-height:calc(100svh - 105px); }
.reel-kicker { color:var(--dim); font-size:11px; letter-spacing:.12em; margin:2px 0 10px; }
.reel-title { margin:0 0 18px; font-size:26px; line-height:1.15; color:var(--bright); }
.reel-card { border:1px solid var(--off); padding:18px; margin:0 0 14px; }
.reel-card.hot { border-color:var(--amber); }
.reel-card.success { border-color:var(--bright); }
.reel-label { color:var(--dim); font-size:10px; letter-spacing:.11em; margin-bottom:8px; }
.reel-big { color:var(--bright); font-size:29px; line-height:1.1; margin:4px 0 8px; }
.reel-value { color:var(--bright); font-size:42px; line-height:1; margin:8px 0; }
.reel-grid { display:grid; grid-template-columns:1fr auto; gap:8px 12px; }
.reel-row { display:grid; grid-template-columns:32px 1fr auto; gap:10px; align-items:center; padding:14px 0; border-bottom:1px dotted var(--off); }
.reel-row:last-child { border-bottom:0; }
.reel-rank { color:var(--dim); }
.reel-score { color:var(--bright); }
.reel-progress { height:8px; border:1px solid var(--off); margin:12px 0 4px; overflow:hidden; }
.reel-progress > span { display:block; height:100%; background:var(--amber); }
.reel-chat { display:grid; gap:14px; margin-top:8px; }
.reel-bubble { max-width:86%; border:1px solid var(--off); padding:14px; line-height:1.45; }
.reel-bubble.out { justify-self:start; }
.reel-bubble.in { justify-self:end; border-color:var(--amber); color:var(--bright); }
.reel-time { display:block; margin-top:7px; font-size:9px; color:var(--dim); }
.reel-check { width:78px; height:78px; border:1px solid var(--bright); border-radius:50%; display:grid; place-items:center; font-size:38px; margin:8px 0 16px; color:var(--bright); }
.reel-spacer { flex:1; min-height:18px; }
.reel-meta { color:var(--dim); font-size:11px; line-height:1.6; }
.reel-controls { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:auto; padding-top:18px; }
.reel-controls.one { grid-template-columns:1fr; }
.reel-step { text-align:center; color:var(--dim); font-size:10px; letter-spacing:.12em; margin-top:10px; }
.reel-capture .reel-controls, .reel-capture .reel-step, .reel-capture .ec-settings-gear, .reel-capture .ec-corner-marks { display:none !important; }
.reel-capture main { padding-bottom:24px !important; }
.reel-cta { border:1px solid var(--bright); padding:18px; text-align:center; color:var(--bright); text-decoration:none; font-size:19px; letter-spacing:.08em; }
.reel-subcta { text-align:center; color:var(--dim); font-size:11px; margin-top:10px; }
</style>
"""


def _require_artist(request: Request) -> dict:
    artist = core.current_artist(request)
    if not artist:
        raise HTTPException(404, "Not found")
    return artist


def _controls(step: int, capture: bool) -> str:
    if capture:
        return ""
    prev_href = f"/owner/reels/example/{step - 1}" if step > 1 else "/owner/reels/example/1"
    next_href = f"/owner/reels/example/{step + 1}" if step < 6 else "/owner/reels/example/1"
    prev_label = "← PREVIOUS" if step > 1 else "RESTART"
    next_label = "NEXT SCREEN →" if step < 6 else "REPLAY →"
    return f"""
      <div class='reel-controls'>
        <a class='button quiet' href='{prev_href}'>{prev_label}</a>
        <a class='button' href='{next_href}'>{next_label}</a>
      </div>
      <div class='reel-step'>SCREEN {step} / 6</div>
    """


def _screen(step: int) -> str:
    if step == 1:
        return """
        <div class='reel-screen'>
          <div class='reel-kicker'>&gt;&gt; CALENDAR EVENT</div>
          <h1 class='reel-title'>APPOINTMENT CANCELLED</h1>
          <div class='reel-card hot'>
            <div class='reel-label'>TODAY // 3:00 PM</div>
            <div class='reel-big'>BLACK &amp; GREY HALF-DAY</div>
            <div class='reel-grid'>
              <span class='dim'>DURATION</span><span>3 HR</span>
              <span class='dim'>APPOINTMENT VALUE</span><span>$450</span>
              <span class='dim'>DEPOSIT</span><span>$100</span>
              <span class='dim'>STATUS</span><span class='bright'>CANCELLED</span>
            </div>
          </div>
          <p class='reel-meta'>Calendar change detected automatically.<br>No post. No story. No group chat.</p>
          <div class='reel-spacer'></div>
          <div class='status'><span>RECOVERY</span><span class='bright'>STARTING...</span></div>
        </div>
        """
    if step == 2:
        return """
        <div class='reel-screen'>
          <div class='reel-kicker'>&gt;&gt; EMPTY CHAIR</div>
          <h1 class='reel-title'>RECOVERY STARTED</h1>
          <div class='reel-card hot'>
            <div class='reel-label'>OPENING // TODAY 3:00 PM</div>
            <div class='reel-big'>FINDING THE BEST REPLACEMENT</div>
            <div class='reel-progress'><span style='width:74%'></span></div>
            <p class='reel-meta'>Checking availability<br>Filtering recent clients<br>Ranking by fit<br>Preparing first offer</p>
          </div>
          <div class='reel-spacer'></div>
          <div class='status'><span>ELIGIBLE CLIENTS</span><span>14</span></div>
          <div class='status'><span>TOP MATCHES</span><span class='bright'>3</span></div>
          <div class='status'><span>STATUS</span><span class='bright'>READY</span></div>
        </div>
        """
    if step == 3:
        return """
        <div class='reel-screen'>
          <div class='reel-kicker'>&gt;&gt; MATCHING</div>
          <h1 class='reel-title'>TOP CLIENTS</h1>
          <div class='reel-card hot'>
            <div class='reel-row'>
              <span class='reel-rank'>01</span><span class='bright'>MAYA</span><span class='reel-score'>92%</span>
            </div>
            <div class='reel-row'>
              <span class='reel-rank'>02</span><span>JORDAN</span><span class='reel-score'>87%</span>
            </div>
            <div class='reel-row'>
              <span class='reel-rank'>03</span><span>ALEX</span><span class='reel-score'>79%</span>
            </div>
          </div>
          <div class='reel-card'>
            <div class='reel-label'>WHY MAYA</div>
            <div class='status'><span>SHORT NOTICE</span><span>[✓]</span></div>
            <div class='status'><span>STYLE FIT</span><span>[✓]</span></div>
            <div class='status'><span>BUDGET FIT</span><span>[✓]</span></div>
            <div class='status'><span>RECENT NO-SHOW</span><span>NONE</span></div>
          </div>
          <div class='reel-spacer'></div>
          <div class='status'><span>FIRST OFFER</span><span class='bright'>MAYA</span></div>
        </div>
        """
    if step == 4:
        return """
        <div class='reel-screen'>
          <div class='reel-kicker'>&gt;&gt; OUTREACH</div>
          <h1 class='reel-title'>OPENING OFFERED</h1>
          <div class='reel-card'>
            <div class='reel-label'>SMS // MAYA</div>
            <div class='reel-chat'>
              <div class='reel-bubble out'>Hey Maya — an opening just came up today at 3:00 PM for a black &amp; grey half-day. Want it?<span class='reel-time'>2:08 PM // SENT</span></div>
              <div class='reel-bubble in'>Yes — I can take it.<span class='reel-time'>2:10 PM // RECEIVED</span></div>
              <div class='reel-bubble out'>Perfect. Your $100 deposit link is ready. Once it’s paid, the 3:00 PM spot is yours.<span class='reel-time'>2:10 PM // SENT</span></div>
            </div>
          </div>
          <div class='reel-spacer'></div>
          <div class='status'><span>CLIENT</span><span class='bright'>CONFIRMED INTEREST</span></div>
          <div class='status'><span>NEXT</span><span>DEPOSIT</span></div>
        </div>
        """
    if step == 5:
        return """
        <div class='reel-screen'>
          <div class='reel-kicker'>&gt;&gt; PAYMENT</div>
          <h1 class='reel-title'>DEPOSIT RECEIVED</h1>
          <div class='reel-card success'>
            <div class='reel-check'>✓</div>
            <div class='reel-label'>PAYMENT COMPLETE</div>
            <div class='reel-value'>$100</div>
            <div class='reel-big'>PAID</div>
          </div>
          <div class='reel-card'>
            <div class='status'><span>CLIENT</span><span>MAYA</span></div>
            <div class='status'><span>APPOINTMENT</span><span>TODAY 3:00 PM</span></div>
            <div class='status'><span>DURATION</span><span>3 HR</span></div>
            <div class='status'><span>DEPOSIT</span><span class='bright'>CONFIRMED</span></div>
          </div>
          <div class='reel-spacer'></div>
          <div class='status'><span>CALENDAR</span><span class='bright'>UPDATING...</span></div>
        </div>
        """
    return """
    <div class='reel-screen'>
      <div class='reel-kicker'>&gt;&gt; RECOVERY COMPLETE</div>
      <h1 class='reel-title success'>CHAIR FILLED</h1>
      <div class='reel-card success'>
        <div class='reel-check'>✓</div>
        <div class='reel-label'>TODAY // 3:00 PM</div>
        <div class='reel-big'>SLOT RECOVERED</div>
        <div class='status'><span>APPOINTMENT VALUE</span><span class='bright'>$450</span></div>
        <div class='status'><span>DEPOSIT RECEIVED</span><span class='bright'>$100</span></div>
        <div class='status'><span>TIME TO FILL</span><span class='bright'>12 MIN</span></div>
      </div>
      <div class='reel-spacer'></div>
      <p class='center bright'>ONE RECOVERED SPOT CAN PAY FOR EMPTY CHAIR.</p>
      <a class='reel-cta' href='/'>7-DAY FREE TRIAL →</a>
      <div class='reel-subcta'>NO CARD REQUIRED</div>
    </div>
    """


@core.app.get("/owner/reels/example")
def reel_example_index(request: Request):
    _require_artist(request)
    return RedirectResponse("/owner/reels/example/1", status_code=303)


@core.app.get("/owner/reels/example/{step}", response_class=HTMLResponse)
def reel_example_screen(request: Request, step: int, capture: int = 0):
    _require_artist(request)
    if step < 1 or step > 6:
        raise HTTPException(404, "Not found")
    capture_mode = bool(capture)
    body = _screen(step) + _controls(step, capture_mode)
    wrapper = f"<div class='{'reel-capture' if capture_mode else ''}'>{body}</div>"
    return core.page(f"Reel Example {step}", wrapper, head=REEL_CSS)


print("Empty Chair Reel demo loaded // 6 full-screen in-app scenario screens", flush=True)
