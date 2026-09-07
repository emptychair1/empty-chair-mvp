"""Give Hunter DM-ready artists distinct, stable conversation openers.

The outreach remains manual. This only changes the copy staged for the founder so the
same canned question is not shown for every artist.
"""
from __future__ import annotations

import hashlib

import v2_hunter_operator as hunter
import v2_hunter_outreach as outreach


OPENERS = (
    "Quick question — what do you usually do when a client cancels a tattoo appointment a few days out?",
    "Curious — if you get a cancellation this week, how do you normally try to fill the spot?",
    "Hey — do last-minute cancellations usually get refilled for you, or do you just eat the open time?",
    "Random tattoo-business question: when a spot opens up last minute, what’s your first move to fill it?",
    "When someone cancels on short notice, do you have a reliable way to fill that chair?",
    "Do you usually post cancellations to Stories, hit a waitlist, or use something else?",
    "How often are you actually able to refill a same-week cancellation?",
    "If tomorrow suddenly opened up, how would you find someone to take the slot?",
    "What’s your go-to when a tattoo appointment drops off the calendar at the last minute?",
    "Do cancellations usually turn into an open chair for you, or can you normally refill them pretty fast?",
)

_ORIGINAL_RENDER = outreach._render_action


def opener_for(target: dict) -> str:
    """Return a deterministic opener so an artist keeps the same copy across reloads."""
    key = str(target.get("account_id") or target.get("username") or "hunter")
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return OPENERS[int.from_bytes(digest[:4], "big") % len(OPENERS)]


def render_action_with_varied_dm(stage: str, target: dict | None) -> str:
    if stage != "DM_READY" or not target:
        return _ORIGINAL_RENDER(stage, target)

    account_id = str(target.get("account_id") or "")
    username_raw = str(target.get("username") or "").strip().lstrip("@")
    username = hunter.esc(username_raw)
    name = hunter.esc(target.get("name") or "")
    context = " // ".join(
        hunter.esc(value)
        for value in (target.get("market"), target.get("activity_source"))
        if value
    )
    native_url, web_url = outreach._instagram_urls(username_raw)
    open_button = (
        f"<button type='button' class='outreach-open' "
        f"data-native='{hunter.esc(native_url)}' data-web='{hunter.esc(web_url)}' "
        f"onclick='openHunterInstagram(this)'>OPEN INSTAGRAM</button>"
    )
    identity = (
        f"<div class='dim'>{name}</div>"
        if name and name.lower() != username.lower()
        else ""
    )
    content = (
        outreach._copy_block(opener_for(target), "OPENER")
        + open_button
        + outreach._action_form(account_id, "DM_SENT", "DM SENT ✓")
    )
    return f"""
      <section class='outreach-card'>
        <div class='outreach-stage'>&gt;&gt; SEND DM</div>
        {identity}
        <h1>@{username}</h1>
        <div class='outreach-context'>{context or 'FOLLOWED TATTOO ARTIST'}</div>
        {content}
      </section>
    """


outreach._render_action = render_action_with_varied_dm

print("Hunter DM variety loaded // stable per-artist openers", flush=True)
