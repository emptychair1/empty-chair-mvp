"""Founder-only Instagram Story Director.

Prepares believable Story sequences for manual Instagram posting. It deliberately does
not counterfeit Instagram interactive stickers: polls/questions/sliders/link stickers
are instructions for the founder to add natively in Instagram.
"""
from __future__ import annotations

import hashlib
import html
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

import v2_app as core
from hunter.operator_auth import is_admin_identity, parse_phones

EASTERN = ZoneInfo("America/New_York")
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("EMPTY_CHAIR_ADMIN_EMAILS", "").split(",") if e.strip()}
ADMIN_PHONES = parse_phones(os.getenv("EMPTY_CHAIR_ADMIN_PHONES", ""))


def _founder(request: Request):
    artist = core.current_artist(request)
    if not artist or not is_admin_identity(artist, admin_emails=ADMIN_EMAILS, admin_phones=ADMIN_PHONES):
        raise HTTPException(404, "Not found")
    return artist


FAMILIES = [
    {
        "name": "CANCELLATION PAIN",
        "frames": [
            ("TEXT", "Tattoo artists — did somebody cancel on you this week?", "POLL", "YEP // SOMEHOW NO"),
            ("TEXT", "What was that appointment worth?", "POLL", "$200–400 // $400+"),
            ("DEMO", "Show the real cancellation → Empty Chair working → calendar refilled sequence.", "NONE", ""),
            ("TEXT", "That's the whole job. Recover the chair.", "LINK", "TRY IT FREE"),
        ],
    },
    {
        "name": "MONEY LOST",
        "frames": [
            ("TEXT", "$500 appointment cancels tomorrow. What happens next?", "QUESTION", "WHAT DOES YOUR SHOP DO?"),
            ("DEMO", "Show the real artist OPEN SMS with value at risk and matches ready.", "NONE", ""),
            ("DEMO", "Show the real filled calendar and real payment result screen.", "NONE", ""),
        ],
    },
    {
        "name": "SHOP QUESTION",
        "frames": [
            ("TEXT", "Do you keep a cancellation list?", "POLL", "YES // I SHOULD"),
            ("TEXT", "How many people on it would actually take a chair today?", "QUESTION", "DROP A NUMBER"),
            ("TEXT", "That's the part Empty Chair is built to work.", "NONE", ""),
        ],
    },
    {
        "name": "PRODUCT DEMO",
        "frames": [
            ("TEXT", "Watch this appointment.", "NONE", ""),
            ("DEMO", "Show a real native calendar cancellation.", "NONE", ""),
            ("DEMO", "Show the real Empty Chair SMS recovery sequence.", "NONE", ""),
            ("DEMO", "Show the real native calendar repopulated and payment landed.", "NONE", ""),
            ("TEXT", "One cancellation. Recovered.", "LINK", "TRY IT FREE"),
        ],
    },
    {
        "name": "FOUNDER OBSERVATION",
        "frames": [
            ("TEXT", "A cancellation shouldn't turn into a night of posting 'books open' everywhere.", "NONE", ""),
            ("TEXT", "The opening already exists. The job is finding the right person fast enough.", "NONE", ""),
            ("TEXT", "That's why I built Empty Chair.", "QUESTION", "HOW DO YOU HANDLE CANCELLATIONS?"),
        ],
    },
    {
        "name": "NO-SELL ENGAGEMENT",
        "frames": [
            ("TEXT", "Tattooers: what's worse?", "POLL", "SAME-DAY CANCEL // NO SHOW"),
            ("TEXT", "How many cancellations did you have last month?", "QUESTION", "DROP A NUMBER"),
        ],
    },
    {
        "name": "SOFT CTA",
        "frames": [
            ("TEXT", "If your calendar loses a chair, how quickly can you actually replace it?", "SLIDER", "😬"),
            ("DEMO", "Show one real Empty Chair recovery sequence. No marketing graphics.", "NONE", ""),
            ("TEXT", "Want it watching your calendar?", "LINK", "TRY EMPTY CHAIR"),
        ],
    },
]


def _today_plan():
    today = datetime.now(EASTERN).date().isoformat()
    idx = int(hashlib.sha256(today.encode()).hexdigest()[:8], 16) % len(FAMILIES)
    return today, FAMILIES[idx]


CSS = """
<style>
.story-wrap{max-width:760px;margin:0 auto}.story-head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin-bottom:20px}.story-head h1{margin:0}.story-note{font-size:11px;color:var(--dim);text-align:right}.director{border:1px solid var(--off);padding:16px;margin-bottom:20px}.director-title{font-size:15px;color:var(--bright);margin-bottom:6px}.rule{font-size:11px;color:var(--dim);line-height:1.55}.frames{display:grid;gap:14px}.frame{border:1px solid var(--off);padding:14px}.frame-top{display:flex;justify-content:space-between;gap:12px;font-size:10px;color:var(--dim);margin-bottom:12px}.frame-copy{font-size:16px;line-height:1.45;color:var(--bright)}.sticker{margin-top:12px;border-top:1px solid var(--off);padding-top:10px;font-size:11px}.sticker b{color:var(--amber)}.guard{margin-top:20px;border:1px dashed var(--off);padding:14px;font-size:11px;color:var(--dim);line-height:1.55}
</style>
"""


@core.app.get("/owner/ig-stories", response_class=HTMLResponse)
def founder_ig_stories(request: Request):
    _founder(request)
    day, plan = _today_plan()
    frames = []
    for n, (kind, copy, sticker, sticker_copy) in enumerate(plan["frames"], 1):
        sticker_html = ""
        if sticker != "NONE":
            sticker_html = f'<div class="sticker"><b>ADD NATIVE {html.escape(sticker)}:</b> {html.escape(sticker_copy)}</div>'
        frames.append(f'''<article class="frame">
          <div class="frame-top"><span>FRAME {n:02d}</span><span>{html.escape(kind)}</span></div>
          <div class="frame-copy">{html.escape(copy)}</div>{sticker_html}
        </article>''')
    body = f"""
    <div class='story-wrap'>
      <div class='story-head'>
        <div><p class='dim' style='margin:0 0 5px'>FOUNDER // CONTENT</p><h1>IG STORIES</h1></div>
        <div class='story-note'>{day}<br>STORY DIRECTOR</div>
      </div>
      <section class='director'>
        <div class='director-title'>{html.escape(plan['name'])}</div>
        <div class='rule'>TODAY'S SEQUENCE // {len(plan['frames'])} FRAMES. Post like a founder, not an ad account.</div>
      </section>
      <div class='frames'>{''.join(frames)}</div>
      <div class='guard'>HUMANITY GOVERNOR // Use only real Empty Chair/native-app screens for demos. Never fake polls, questions, sliders, links, customer results, payments, or product behavior. Instagram stickers are added natively at posting time. CTA frequency varies by narrative.</div>
    </div>
    """
    return core.page("IG Stories", body, head=CSS)


print("Instagram Story Director loaded // founder-only // native sticker instructions", flush=True)
