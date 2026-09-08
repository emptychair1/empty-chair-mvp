"""Founder-only Instagram Story Director."""
from __future__ import annotations
import hashlib, html, os
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
import v2_app as core
from hunter.operator_auth import is_admin_identity, parse_phones
EASTERN=ZoneInfo("America/New_York")
ADMIN_EMAILS={e.strip().lower() for e in os.getenv("EMPTY_CHAIR_ADMIN_EMAILS","").split(",") if e.strip()}
ADMIN_PHONES=parse_phones(os.getenv("EMPTY_CHAIR_ADMIN_PHONES",""))

def _founder(request):
    artist=core.current_artist(request)
    if not artist or not is_admin_identity(artist,admin_emails=ADMIN_EMAILS,admin_phones=ADMIN_PHONES): raise HTTPException(404,"Not found")
    return artist

# Stable, image-CDN-hosted tattoo-world backgrounds. These are decorative atmosphere only.
# The img element has an on-page fallback so a failed source can never silently disappear.
BACKGROUNDS=[
 {"label":"TATTOO STUDIO","url":"https://images.unsplash.com/photo-1568515045052-f9a854d70bfd?auto=format&fit=crop&w=1080&h=1920&q=85"},
 {"label":"TATTOO WORKSPACE","url":"https://images.unsplash.com/photo-1590246814883-57c511e91b28?auto=format&fit=crop&w=1080&h=1920&q=85"},
 {"label":"TATTOO ARTIST","url":"https://images.unsplash.com/photo-1611501275019-9b5cda994e8d?auto=format&fit=crop&w=1080&h=1920&q=85"},
]
FAMILIES=[
 {"name":"CANCELLATION PAIN","frames":[("TEXT","Tattoo artists — did somebody cancel on you this week?","POLL","YEP // SOMEHOW NO"),("TEXT","What was that appointment worth?","POLL","$200–400 // $400+"),("DEMO","Show the real cancellation → Empty Chair working → calendar refilled sequence.","NONE",""),("TEXT","That's the whole job. Recover the chair.","LINK","TRY IT FREE")]},
 {"name":"MONEY LOST","frames":[("TEXT","$500 appointment cancels tomorrow. What happens next?","QUESTION","WHAT DOES YOUR SHOP DO?"),("DEMO","Show the real artist OPEN SMS with value at risk and matches ready.","NONE",""),("DEMO","Show the real filled calendar and real payment result screen.","NONE","")]},
 {"name":"SHOP QUESTION","frames":[("TEXT","Do you keep a cancellation list?","POLL","YES // I SHOULD"),("TEXT","How many people on it would actually take a chair today?","QUESTION","DROP A NUMBER"),("TEXT","That's the part Empty Chair is built to work.","NONE","")]},
 {"name":"PRODUCT DEMO","frames":[("TEXT","Watch this appointment.","NONE",""),("DEMO","Show a real native calendar cancellation.","NONE",""),("DEMO","Show the real Empty Chair SMS recovery sequence.","NONE",""),("DEMO","Show the real native calendar repopulated and payment landed.","NONE",""),("TEXT","One cancellation. Recovered.","LINK","TRY IT FREE")]},
 {"name":"FOUNDER OBSERVATION","frames":[("TEXT","A cancellation shouldn't turn into a night of posting 'books open' everywhere.","NONE",""),("TEXT","The opening already exists. The job is finding the right person fast enough.","NONE",""),("TEXT","That's why I built Empty Chair.","QUESTION","HOW DO YOU HANDLE CANCELLATIONS?")]},
 {"name":"NO-SELL ENGAGEMENT","frames":[("TEXT","Tattooers: what's worse?","POLL","SAME-DAY CANCEL // NO SHOW"),("TEXT","How many cancellations did you have last month?","QUESTION","DROP A NUMBER")]},
 {"name":"SOFT CTA","frames":[("TEXT","If your calendar loses a chair, how quickly can you actually replace it?","SLIDER","😬"),("DEMO","Show one real Empty Chair recovery sequence. No marketing graphics.","NONE",""),("TEXT","Want it watching your calendar?","LINK","TRY EMPTY CHAIR")]},
]
def _today_plan():
    today=datetime.now(EASTERN).date().isoformat(); seed=int(hashlib.sha256(today.encode()).hexdigest()[:8],16)
    return today,FAMILIES[seed%len(FAMILIES)],BACKGROUNDS[seed%len(BACKGROUNDS)]
CSS="""<style>.story-wrap{max-width:760px;margin:0 auto}.story-head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin-bottom:20px}.story-head h1{margin:0}.story-note{font-size:11px;color:var(--dim);text-align:right}.director{border:1px solid var(--off);padding:16px;margin-bottom:20px}.director-title{font-size:15px;color:var(--bright);margin-bottom:6px}.rule{font-size:11px;color:var(--dim);line-height:1.55}.bg-card{border:1px solid var(--off);margin-bottom:20px;overflow:hidden;background:#080706}.bg-photo{display:block;width:100%;height:420px;object-fit:cover;background:linear-gradient(135deg,#1c1710,#050403)}.bg-meta{padding:12px 14px;font-size:10px;color:var(--dim)}.frames{display:grid;gap:14px}.frame{border:1px solid var(--off);padding:14px}.frame-top{display:flex;justify-content:space-between;gap:12px;font-size:10px;color:var(--dim);margin-bottom:12px}.frame-copy{font-size:16px;line-height:1.45;color:var(--bright)}.sticker{margin-top:12px;border-top:1px solid var(--off);padding-top:10px;font-size:11px}.sticker b{color:var(--amber)}.guard{margin-top:20px;border:1px dashed var(--off);padding:14px;font-size:11px;color:var(--dim);line-height:1.55}</style>"""
@core.app.get("/owner/ig-stories",response_class=HTMLResponse)
def founder_ig_stories(request:Request):
    _founder(request); day,plan,bg=_today_plan(); frames=[]
    for n,(kind,copy,sticker,sticker_copy) in enumerate(plan["frames"],1):
        sticker_html="" if sticker=="NONE" else f'<div class="sticker"><b>ADD NATIVE {html.escape(sticker)}:</b> {html.escape(sticker_copy)}</div>'
        frames.append(f'<article class="frame"><div class="frame-top"><span>FRAME {n:02d}</span><span>{html.escape(kind)}</span></div><div class="frame-copy">{html.escape(copy)}</div>{sticker_html}</article>')
    bg_url=html.escape(bg["url"],quote=True)
    body=f"""<div class='story-wrap'><div class='story-head'><div><p class='dim' style='margin:0 0 5px'>FOUNDER // CONTENT</p><h1>IG STORIES</h1></div><div class='story-note'>{day}<br>STORY DIRECTOR</div></div><section class='director'><div class='director-title'>{html.escape(plan['name'])}</div><div class='rule'>TODAY'S SEQUENCE // {len(plan['frames'])} FRAMES. One background anchors today's text frames.</div></section><section class='bg-card'><img class='bg-photo' src='{bg_url}' alt="Today's stock tattoo background" referrerpolicy='no-referrer' onerror="this.onerror=null;this.src='https://images.unsplash.com/photo-1568515045052-f9a854d70bfd?auto=format&fit=crop&w=1080&h=1920&q=85';"><div class='bg-meta'>TODAY'S STOCK BACKGROUND // {html.escape(bg['label'])} // STOCK PHOTO</div></section><div class='frames'>{''.join(frames)}</div><div class='guard'>HUMANITY GOVERNOR // Stock imagery is atmosphere only. Use real Empty Chair/native-app screens for demos. Never fake stickers, customer results, payments, or product behavior. Instagram interactions are added natively at posting time.</div></div>"""
    return core.page("IG Stories",body,head=CSS)
print("Instagram Story Director loaded // reliable daily stock background + native sticker instructions",flush=True)
