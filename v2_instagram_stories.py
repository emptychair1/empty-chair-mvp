"""Founder-only Instagram Story Director: a literal daily posting guide."""
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

BACKGROUNDS=[
 {"label":"TATTOO STUDIO","url":"https://images.unsplash.com/photo-1568515045052-f9a854d70bfd?auto=format&fit=crop&w=1080&h=1920&q=85"},
 {"label":"TATTOO WORKSPACE","url":"https://images.unsplash.com/photo-1590246814883-57c511e91b28?auto=format&fit=crop&w=1080&h=1920&q=85"},
 {"label":"TATTOO ARTIST","url":"https://images.unsplash.com/photo-1611501275019-9b5cda994e8d?auto=format&fit=crop&w=1080&h=1920&q=85"},
]
FAMILIES=[
 {"name":"CANCELLATION PAIN","frames":[("Tattoo artists — did somebody cancel on you this week?","POLL","YEP","SOMEHOW NO"),("What was that appointment worth?","POLL","$200–400","$400+"),("That's the whole job. Recover the chair.","LINK","TRY IT FREE","")]},
 {"name":"SHOP QUESTION","frames":[("Do you keep a cancellation list?","POLL","YES","I SHOULD"),("How many people on it would actually take a chair today?","QUESTION","DROP A NUMBER","")]},
 {"name":"FOUNDER OBSERVATION","frames":[("A cancellation shouldn't turn into a night of posting 'books open' everywhere.","NONE","","") ,("The opening already exists. The job is finding the right person fast enough.","NONE","","") ,("That's why I built Empty Chair.","QUESTION","HOW DO YOU HANDLE CANCELLATIONS?","")]},
 {"name":"NO-SELL ENGAGEMENT","frames":[("Tattooers: what's worse?","POLL","SAME-DAY CANCEL","NO SHOW"),("How many cancellations did you have last month?","QUESTION","DROP A NUMBER","")]},
 {"name":"SOFT CTA","frames":[("If your calendar loses a chair, how quickly can you actually replace it?","SLIDER","😬","") ,("Want Empty Chair watching your calendar?","LINK","TRY EMPTY CHAIR","")]},
]
def _today_plan():
    today=datetime.now(EASTERN).date().isoformat(); seed=int(hashlib.sha256(today.encode()).hexdigest()[:8],16)
    return today,FAMILIES[seed%len(FAMILIES)],BACKGROUNDS[seed%len(BACKGROUNDS)]

def _sticker_instruction(kind,a,b):
    if kind=="NONE": return "Don't add a sticker to this one."
    if kind=="POLL": return f"Tap Stickers → Poll. Enter: {a} / {b}."
    if kind=="QUESTION": return f"Tap Stickers → Questions. Prompt: {a}."
    if kind=="SLIDER": return f"Tap Stickers → Emoji slider. Use: {a}."
    if kind=="LINK": return f"Tap Stickers → Link. Link to tryemptychair.com and label it: {a}."
    return ""
CSS="""<style>.story-wrap{max-width:760px;margin:0 auto}.story-head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin-bottom:20px}.story-head h1{margin:0}.story-note{font-size:11px;color:var(--dim);text-align:right}.intro{border:1px solid var(--amber);padding:16px;margin-bottom:18px}.intro strong{color:var(--bright)}.bg-card{border:1px solid var(--off);margin-bottom:20px;overflow:hidden}.bg-photo{display:block;width:100%;height:360px;object-fit:cover;background:#080706}.bg-meta{padding:12px 14px;font-size:10px;color:var(--dim)}.story-card{border:1px solid var(--off);padding:16px;margin-bottom:18px}.story-num{font-size:12px;color:var(--amber);margin-bottom:12px}.mock{aspect-ratio:9/16;max-height:520px;position:relative;overflow:hidden;border:1px solid var(--off);margin:0 auto 16px;background:#080706}.mock img{width:100%;height:100%;object-fit:cover;opacity:.55}.mock-copy{position:absolute;left:10%;right:10%;top:34%;text-align:center;color:#fff;font-family:Arial,sans-serif;font-weight:700;font-size:22px;line-height:1.2;text-shadow:0 2px 12px #000}.mock-sticker{position:absolute;left:14%;right:14%;top:57%;background:#fff;color:#111;border-radius:12px;padding:12px;text-align:center;font-family:Arial,sans-serif;font-weight:700;font-size:13px}.steps{display:grid;gap:9px}.step{border-top:1px solid var(--off);padding-top:9px;font-size:13px;line-height:1.5}.step b{color:var(--amber)}.copybox{margin-top:8px;padding:10px;border:1px dashed var(--off);color:var(--bright)}.guard{margin-top:20px;font-size:11px;color:var(--dim);line-height:1.55}</style>"""
@core.app.get("/owner/ig-stories",response_class=HTMLResponse)
def founder_ig_stories(request:Request):
    _founder(request); day,plan,bg=_today_plan(); bg_url=html.escape(bg["url"],quote=True); cards=[]
    for n,(copy,kind,a,b) in enumerate(plan["frames"],1):
        sticker_preview="" if kind=="NONE" else f'<div class="mock-sticker">{html.escape(a)}{(" &nbsp; | &nbsp; "+html.escape(b)) if b else ""}</div>'
        cards.append(f'''<section class="story-card"><div class="story-num">STORY {n} OF {len(plan['frames'])}</div><div class="mock"><img src="{bg_url}" alt="story background"><div class="mock-copy">{html.escape(copy)}</div>{sticker_preview}</div><div class="steps"><div class="step"><b>1.</b> Open Instagram → tap + → Story.</div><div class="step"><b>2.</b> Use today's background photo shown above.</div><div class="step"><b>3.</b> Tap Aa and type exactly:<div class="copybox">{html.escape(copy)}</div></div><div class="step"><b>4.</b> {html.escape(_sticker_instruction(kind,a,b))}</div><div class="step"><b>5.</b> Tap Your Story to post.</div></div></section>''')
    body=f'''<div class="story-wrap"><div class="story-head"><div><p class="dim" style="margin:0 0 5px">FOUNDER // CONTENT</p><h1>IG STORIES</h1></div><div class="story-note">{day}<br>{html.escape(plan['name'])}</div></div><div class="intro"><strong>DO THIS IN ORDER.</strong><br>You do not need to design anything. Each card below shows roughly what the finished Story should look like and tells you exactly what to tap.</div><section class="bg-card"><img class="bg-photo" src="{bg_url}" alt="Today's stock tattoo background"><div class="bg-meta">TODAY'S BACKGROUND // {html.escape(bg['label'])} // use this same photo for today's sequence</div></section>{''.join(cards)}<div class="guard">Stories disappear after 24 hours unless you save them to a Highlight. The mockups are placement guides only; polls, questions, sliders and links must be added with Instagram's real native stickers.</div></div>'''
    return core.page("IG Stories",body,head=CSS)
print("Instagram Story Director loaded // literal posting guide + visual mockups",flush=True)
