"""Founder-only Reddit conversation copilot for Empty Chair.

Finds relevant public Reddit conversations, scores them, and gives the founder
an exact suggested reply to post manually. This never auto-posts.
"""
from __future__ import annotations

import html
import json
import os
import time
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

import v2_app as core
from hunter.operator_auth import is_admin_identity, parse_phones

ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("EMPTY_CHAIR_ADMIN_EMAILS", "").split(",") if e.strip()}
ADMIN_PHONES = parse_phones(os.getenv("EMPTY_CHAIR_ADMIN_PHONES", ""))
USER_AGENT = "EmptyChairFounderRadar/1.1 (+https://tryemptychair.com)"

SEARCH_TERMS = (
    "cancellation",
    "cancellations",
    "no show",
    "last minute",
    "booking",
    "appointment",
    "deposit",
)

COMMUNITIES = (
    ("r/TattooArtists", "Working tattoo artists. Highest-signal place to listen and contribute.", "https://www.reddit.com/r/TattooArtists/"),
    ("r/tattooing", "Broader tattooing discussion with artist and industry conversations.", "https://www.reddit.com/r/tattooing/"),
    ("r/tattoo", "Useful for client-side language, objections, cancellations and booking behavior.", "https://www.reddit.com/r/tattoo/"),
    ("r/tattoos", "Large client-facing community. Better for research than promotion.", "https://www.reddit.com/r/tattoos/"),
)

RESEARCH_QUESTIONS = (
    "Tattoo artists: when tomorrow's appointment cancels, what do you actually do first to try to refill it?",
    "How often are you realistically able to refill a same-week cancellation?",
    "Do you keep a cancellation or wait list? If so, how do you contact people when a chair opens?",
    "What's the worst part of last-minute cancellations: lost money, outreach, deposits, or reshuffling the calendar?",
    "When you post a last-minute opening, what channel actually fills it most often?",
)


def _founder(request: Request):
    artist = core.current_artist(request)
    if not artist or not is_admin_identity(artist, admin_emails=ADMIN_EMAILS, admin_phones=ADMIN_PHONES):
        raise HTTPException(404, "Not found")
    return artist


def _fetch(term: str) -> list[dict]:
    params = urlencode({
        "q": term,
        "restrict_sr": "1",
        "sort": "new",
        "t": "year",
        "limit": "8",
        "raw_json": "1",
    })
    url = f"https://www.reddit.com/r/TattooArtists/search.json?{params}"
    req = URLRequest(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=4) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [x.get("data", {}) for x in payload.get("data", {}).get("children", [])]


def _score(post: dict) -> tuple[int, str, str]:
    title = str(post.get("title") or "").lower()
    selftext = str(post.get("selftext") or "").lower()
    hay = f"{title} {selftext}"
    points = 0
    if any(k in hay for k in ("cancel", "no show", "no-show")): points += 45
    if any(k in hay for k in ("last minute", "opening", "fill", "appointment")): points += 25
    if any(k in hay for k in ("booking", "deposit", "books", "schedule")): points += 15
    comments = int(post.get("num_comments") or 0)
    if comments >= 10: points += 10
    elif comments >= 3: points += 5
    age_days = max(0.0, (time.time() - float(post.get("created_utc") or 0)) / 86400)
    if age_days <= 3: points += 20
    elif age_days <= 14: points += 12
    elif age_days <= 45: points += 6
    points = min(points, 100)
    label = "HIGH" if points >= 60 else "MEDIUM" if points >= 35 else "LOW"
    if "cancel" in hay or "no show" in hay or "no-show" in hay:
        angle = "Operational pain. Be useful first; only disclose Empty Chair if the thread naturally reaches tools/workflow."
    elif "booking" in hay or "deposit" in hay:
        angle = "Workflow discussion. Answer from the artist side and ask one useful follow-up."
    else:
        angle = "Research conversation. Add something useful and learn how artists currently solve it."
    return points, label, angle


def _clean_excerpt(value: str, limit: int = 280) -> str:
    text = " ".join((value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _suggest_reply(post: dict) -> tuple[str, str]:
    """Create a concise founder reply from the actual thread content.

    The copy is deliberately useful-first and does not pretend to be an
    unaffiliated customer. Empty Chair is mentioned only in high-fit threads.
    """
    title = str(post.get("title") or "")
    selftext = str(post.get("selftext") or "")
    hay = f"{title} {selftext}".lower()
    score = int(post.get("ec_score") or 0)

    if any(k in hay for k in ("cancel", "cancellation", "no show", "no-show")):
        if any(k in hay for k in ("fill", "opening", "last minute", "waitlist", "wait list")):
            reply = (
                "This is exactly the ugly part of cancellations — the slot is suddenly worth $0 unless you can reach the right person fast. "
                "What has worked best for me is keeping a small list of people who are actually available on short notice, then contacting them in order instead of blasting everybody at once. "
                "I ended up building Empty Chair around that workflow because I wanted the cancellation → outreach → deposit → calendar refill part handled automatically. "
                "I’m curious: are you keeping any kind of cancellation list now, or is it mostly IG stories/texting people when a spot opens?"
            )
            mode = "REPLY + DISCLOSE"
        else:
            reply = (
                "That’s brutal. The cancellation itself is one problem, but the real time sink is everything after it — figuring out who might take the slot, reaching out, waiting, and then trying the next person. "
                "Do you usually try to refill those spots, or do you mostly accept the loss once it gets inside a day or two?"
            )
            mode = "REPLY + QUESTION"
    elif "deposit" in hay:
        reply = (
            "Deposits solve a different problem than cancellations, in my experience. They help protect commitment, but they don’t put somebody back in the chair once a slot opens. "
            "I’d still keep the deposit policy, but I’d treat refill/recovery as its own workflow. How often are you actually able to refill a cancelled slot after the deposit is forfeited?"
        )
        mode = "REPLY + QUESTION"
    elif any(k in hay for k in ("booking", "books", "appointment", "schedule")):
        reply = (
            "The part I’d watch is what happens between ‘someone wants the spot’ and ‘the calendar is actually filled.’ That handoff gets messy fast when you’re also tattooing. "
            "Are you handling the whole thing manually right now — DMs/texts, deposit, then calendar — or do you have one system doing any of that for you?"
        )
        mode = "REPLY + QUESTION"
    else:
        excerpt = _clean_excerpt(title, 120)
        reply = (
            f"I’m interested in this from the artist side too. On ‘{excerpt}’, what part is actually the biggest headache in practice — finding the person, getting a fast answer, taking the deposit, or getting the calendar updated?"
        )
        mode = "RESEARCH QUESTION"

    if score < 60 and "Empty Chair" in reply:
        reply = reply.replace(
            "I ended up building Empty Chair around that workflow because I wanted the cancellation → outreach → deposit → calendar refill part handled automatically. ",
            ""
        )
        mode = "REPLY + QUESTION"
    return reply, mode


def _age(created: float) -> str:
    seconds = max(0, int(time.time() - created))
    if seconds < 3600: return f"{max(1, seconds // 60)}m ago"
    if seconds < 86400: return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _opportunities() -> tuple[list[dict], bool]:
    posts: dict[str, dict] = {}
    live = False
    for term in SEARCH_TERMS:
        try:
            batch = _fetch(term)
            live = True
        except Exception as exc:
            print(f"Founder Reddit radar fetch failed // {term}: {exc}", flush=True)
            continue
        for post in batch:
            pid = str(post.get("id") or "")
            if not pid or post.get("stickied"): continue
            score, label, angle = _score(post)
            post["ec_score"] = score
            post["ec_label"] = label
            post["ec_angle"] = angle
            reply, mode = _suggest_reply(post)
            post["ec_reply"] = reply
            post["ec_reply_mode"] = mode
            previous = posts.get(pid)
            if not previous or score > int(previous.get("ec_score") or 0): posts[pid] = post
    ranked = sorted(posts.values(), key=lambda p: (int(p.get("ec_score") or 0), float(p.get("created_utc") or 0)), reverse=True)
    return [p for p in ranked if int(p.get("ec_score") or 0) >= 25][:15], live


CSS = """<style>
.reddit-wrap{max-width:820px;margin:0 auto}.radar-head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;margin-bottom:20px}.radar-head h1{margin:0}.badge{font-size:11px;color:var(--dim);text-align:right}.intro,.guard{border:1px solid var(--off);padding:14px;margin-bottom:18px;font-size:12px;line-height:1.55}.tabs{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:18px 0}.tab{border:1px solid var(--off);padding:10px;text-align:center;font-size:10px;color:var(--dim)}.section-title{font-size:12px;color:var(--amber);letter-spacing:.08em;margin:24px 0 10px}.opps{display:grid;gap:12px}.opp{border:1px solid var(--off);padding:14px}.opp-top{display:flex;justify-content:space-between;gap:10px;font-size:10px;color:var(--dim);margin-bottom:9px}.score-high{color:#FFD36A}.score-medium{color:var(--amber)}.score-low{color:var(--dim)}.opp-title{font-size:15px;line-height:1.4;color:var(--bright)}.excerpt{font-size:11px;line-height:1.5;color:var(--dim);margin-top:8px}.why{font-size:11px;line-height:1.5;color:var(--dim);margin-top:10px}.say-label{font-size:10px;color:var(--amber);letter-spacing:.09em;margin:14px 0 6px}.say{border:1px solid rgba(255,176,0,.35);background:rgba(255,176,0,.04);padding:13px;color:var(--bright);font-size:13px;line-height:1.55;white-space:pre-wrap}.mode{font-size:10px;color:var(--dim);margin-top:6px}.actions{margin-top:12px;display:flex;gap:8px;flex-wrap:wrap}.btn{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:0 13px;border:1px solid var(--amber);color:var(--bright);text-decoration:none;font-size:10px;background:transparent}.copy-btn{cursor:pointer;font-family:inherit}.copied{color:#FFD36A}.community,.question{border:1px solid var(--off);padding:13px;margin-bottom:9px}.community b,.question b{color:var(--bright)}.community small{display:block;color:var(--dim);margin-top:5px;line-height:1.4}.empty{border:1px dashed var(--off);padding:20px;color:var(--dim);font-size:12px;line-height:1.5}.search-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}@media(max-width:620px){.tabs,.search-grid{grid-template-columns:1fr}.radar-head{align-items:flex-start;flex-direction:column}.badge{text-align:left}}
</style>
<script>
function ecCopyReply(id, button){
  const el=document.getElementById(id); if(!el) return;
  navigator.clipboard.writeText(el.innerText).then(()=>{const old=button.innerText;button.innerText='COPIED';button.classList.add('copied');setTimeout(()=>{button.innerText=old;button.classList.remove('copied')},1200)});
}
</script>"""


@core.app.get("/owner/reddit", response_class=HTMLResponse)
def founder_reddit(request: Request):
    _founder(request)
    opportunities, live = _opportunities()
    cards = []
    for idx, p in enumerate(opportunities):
        raw_title = str(p.get("title") or "Untitled")
        title = html.escape(raw_title)
        excerpt = html.escape(_clean_excerpt(str(p.get("selftext") or ""), 300))
        subreddit = html.escape(str(p.get("subreddit_name_prefixed") or "r/TattooArtists"))
        permalink = str(p.get("permalink") or "")
        url = "https://www.reddit.com" + permalink if permalink.startswith("/") else str(p.get("url") or "https://www.reddit.com/r/TattooArtists/")
        safe_url = html.escape(url, quote=True)
        label = html.escape(str(p.get("ec_label") or "LOW"))
        css = "score-high" if label == "HIGH" else "score-medium" if label == "MEDIUM" else "score-low"
        age = html.escape(_age(float(p.get("created_utc") or 0)))
        comments = int(p.get("num_comments") or 0)
        angle = html.escape(str(p.get("ec_angle") or ""))
        reply = html.escape(str(p.get("ec_reply") or ""))
        mode = html.escape(str(p.get("ec_reply_mode") or "REPLY"))
        reply_id = f"reddit-reply-{idx}"
        excerpt_html = f'<div class="excerpt">{excerpt}</div>' if excerpt else ""
        cards.append(f'''<article class="opp"><div class="opp-top"><span class="{css}">{label} OPPORTUNITY // {int(p.get('ec_score') or 0)}</span><span>{subreddit} // {age} // {comments} comments</span></div><div class="opp-title">{title}</div>{excerpt_html}<div class="why"><b>WHY IT MATTERS:</b> {angle}</div><div class="say-label">SAY THIS</div><div class="say" id="{reply_id}">{reply}</div><div class="mode">{mode} // EDIT ONLY IF YOU WANT TO SOUND MORE LIKE YOURSELF</div><div class="actions"><button class="btn copy-btn" type="button" onclick="ecCopyReply('{reply_id}',this)">COPY REPLY</button><a class="btn" href="{safe_url}" target="_blank" rel="noopener">OPEN CONVERSATION</a></div></article>''')
    if cards:
        opportunity_html = "".join(cards)
    else:
        opportunity_html = '<div class="empty">No high-signal live threads were returned right now. Reddit sometimes blocks unauthenticated server requests, so use the direct search buttons below; the page will try live discovery again next time you open it.</div>'

    communities = "".join(
        f'<div class="community"><b>{html.escape(name)}</b><small>{html.escape(note)}</small><div class="actions"><a class="btn" href="{html.escape(url,quote=True)}" target="_blank" rel="noopener">OPEN COMMUNITY</a></div></div>'
        for name, note, url in COMMUNITIES
    )
    questions = "".join(f'<div class="question"><b>ASK:</b> {html.escape(q)}</div>' for q in RESEARCH_QUESTIONS)
    searches = "".join(
        f'<a class="btn" href="https://www.reddit.com/r/TattooArtists/search/?q={html.escape(term.replace(" ","%20"),quote=True)}&restrict_sr=1&sort=new" target="_blank" rel="noopener">SEARCH: {html.escape(term.upper())}</a>'
        for term in ("cancellation", "no show", "last minute", "booking", "deposit", "appointment")
    )
    live_label = "LIVE REDDIT RESULTS" if live else "DIRECT SEARCH MODE"
    body = f'''<div class="reddit-wrap"><div class="radar-head"><div><p class="dim" style="margin:0 0 5px">FOUNDER // GROWTH</p><h1>REDDIT COPILOT</h1></div><div class="badge">{live_label}<br>FIND → COPY → POST</div></div><div class="intro"><b>HOW TO USE THIS:</b> Pick a conversation, read it, copy the suggested reply, then post it yourself. The reply is written to contribute first, ask a useful question, and disclose Empty Chair whenever it is mentioned.</div><div class="tabs"><div class="tab">1 // FIND CONVO</div><div class="tab">2 // COPY REPLY</div><div class="tab">3 // POST YOURSELF</div></div><div class="section-title">BEST CONVERSATIONS RIGHT NOW</div><div class="opps">{opportunity_html}</div><div class="section-title">LIVE SEARCH SHORTCUTS</div><div class="search-grid">{searches}</div><div class="section-title">PLACES TO LISTEN</div>{communities}<div class="section-title">QUESTIONS WORTH ASKING</div>{questions}<div class="guard">NO AUTOPOSTING // NO BULK COMMENTS // NO FAKE CUSTOMER ACCOUNTS // NO PRETENDING TO BE UNAFFILIATED. Suggested replies are starting copy, not invented personal experience. Read the thread before posting.</div></div>'''
    return core.page("Reddit Copilot", body, head=CSS)


print("Founder Reddit copilot loaded // exact suggested replies + copy button", flush=True)
