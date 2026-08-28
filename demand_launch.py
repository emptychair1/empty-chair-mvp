"""Channel-specific launch packages and assisted distribution for Demand Engine."""
import html
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import demand_acquisition


CHANNEL_META = {
    "facebook_marketplace": {"label": "Facebook Marketplace", "open": "https://www.facebook.com/marketplace/create/item"},
    "facebook_group": {"label": "Facebook Groups", "open": "https://www.facebook.com/groups/feed/"},
    "facebook_profile": {"label": "Facebook Profile", "open": "https://www.facebook.com/"},
    "instagram_post": {"label": "Instagram Post", "open": "https://www.instagram.com/"},
    "instagram_reel": {"label": "Instagram Reel", "open": "https://www.instagram.com/"},
    "instagram_story": {"label": "Instagram Story", "open": "https://www.instagram.com/"},
    "reddit": {"label": "Reddit", "open": "https://www.reddit.com/submit"},
    "tiktok": {"label": "TikTok", "open": "https://www.tiktok.com/upload"},
    "referral": {"label": "Referral / Direct Share", "open": ""},
    "qr": {"label": "QR / Physical", "open": ""},
    "other": {"label": "Other", "open": ""},
}


def _e(value):
    return html.escape(str(value or ""), quote=True)


def _package(campaign, tracked_url):
    artist = campaign["artist_name"] or "the artist"
    studio = campaign["studio_name"] or "the studio"
    hook = campaign["hook"] or campaign["name"]
    channel = campaign["channel"] or "other"
    title = f"{campaign['name']} — Athens"

    if channel == "facebook_marketplace":
        copy = (
            f"{hook}. Work by {artist}, currently tattooing at {studio} in Athens. "
            "Send your idea, placement, approximate size, budget and timing through Tattoo Concierge to see if it is a fit."
        )
        cta = f"Interested? Go to {tracked_url.replace('https://', '').replace('http://', '')} and tell me what you want."
        guidance = "Use the title, description and tracked link in the listing. Marketplace review and category eligibility still apply."
    elif channel == "facebook_group":
        copy = (
            f"Athens — {hook}. I'm {artist}, tattooing at {studio}. "
            "If you've been thinking about getting tattooed, send the idea, placement, size, budget and timing through my Tattoo Concierge."
        )
        cta = f"Start here: {tracked_url}"
        guidance = "Post only in groups where self-promotion or local service posts are allowed. Follow each group's rules."
    elif channel == "facebook_profile":
        copy = f"Athens friends: {hook}. I'm taking tattoo inquiries at {studio}. Tell me what you want and I'll see if it's a fit."
        cta = f"Tattoo Concierge: {tracked_url}"
        guidance = "Best for your own profile or page. Pair it with one strong portfolio image that matches the campaign concept."
    elif channel == "instagram_post":
        copy = f"{hook}. Athens, GA · {artist} @ {studio}. Custom and flash inquiries welcome."
        cta = f"Tattoo Concierge: {tracked_url}"
        guidance = "Use a matching portfolio image or carousel. Put the tracked link where your account can make it usable, and keep the caption concise."
    elif channel == "instagram_reel":
        copy = f"{campaign['name']} ideas I want to tattoo in Athens. {artist} @ {studio}."
        cta = f"Want one? Tattoo Concierge: {tracked_url}"
        guidance = "Use a short portfolio montage or process clip. The opening seconds should show the exact subject/style this campaign is testing."
    elif channel == "instagram_story":
        copy = f"ATHENS — {campaign['name']}\n{hook}"
        cta = f"Tell me your idea: {tracked_url}"
        guidance = "Use a matching portfolio image and add the tracked link with the platform's link sticker when available."
    elif channel == "reddit":
        copy = (
            f"Athens-area tattoo artist here. {hook}. I'm currently tattooing at {studio}. "
            "If the community allows local artist posts, I'm happy to answer questions and take inquiries through the link below."
        )
        cta = tracked_url
        guidance = "Only post where the subreddit rules permit artist promotion or local service posts. Avoid repeating the same post across communities."
    elif channel == "tiktok":
        copy = f"Tattoo ideas I want to do in Athens: {campaign['name']}. {artist} @ {studio}."
        cta = f"Tattoo Concierge: {tracked_url}"
        guidance = "Use a fast visual of matching portfolio work. Keep the on-screen idea specific to this campaign so attribution remains useful."
    elif channel == "referral":
        copy = f"Know someone in Athens who'd like this? {hook}. {artist} is tattooing at {studio}."
        cta = f"Send them here: {tracked_url}"
        guidance = "Use the native Share button below to text, AirDrop or send through any app while preserving the tracked campaign link."
    elif channel == "qr":
        copy = f"{campaign['name']} · Athens\n{artist} @ {studio}"
        cta = tracked_url
        guidance = "Use the tracked URL as the QR destination on a printed flash sheet, counter card, sticker or event handout."
    else:
        copy = f"{hook}. {artist} @ {studio} in Athens."
        cta = tracked_url
        guidance = "Use this tracked package in the channel you selected and keep the campaign concept unchanged so results remain comparable."

    full = f"{title}\n\n{copy}\n\n{cta}"
    return title, copy, cta, guidance, full


@core.app.get("/demand-acquisition/launch", response_class=HTMLResponse)
def demand_launch_console(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        demand_acquisition._ensure_tables(conn)
        campaigns = core.db_fetchall(
            conn,
            """SELECT c.*, i.artist_name, i.studio_name
               FROM acquisition_campaigns c
               LEFT JOIN acquisition_identities i ON i.id=c.identity_id
               WHERE c.shop_id=? AND c.status='active'
               ORDER BY c.channel, c.created_at DESC""",
            (user["shop_id"],),
        )
    except Exception:
        conn.rollback()
        campaigns = []
    finally:
        conn.close()

    groups = {}
    for campaign in campaigns:
        groups.setdefault(campaign["channel"] or "other", []).append(campaign)

    sections = []
    for channel, rows in groups.items():
        meta = CHANNEL_META.get(channel, CHANNEL_META["other"])
        cards = []
        for campaign in rows:
            tracked_url = demand_acquisition._campaign_url(request, campaign)
            title, copy, cta, guidance, full = _package(campaign, tracked_url)
            cid = _e(campaign["id"])
            open_button = ""
            if meta["open"]:
                destination = meta["open"]
                if channel == "reddit":
                    destination = f"https://www.reddit.com/submit?url={quote(tracked_url, safe='')}&title={quote(title, safe='')}"
                open_button = f"<a class='button secondary' href='{_e(destination)}' target='_blank' rel='noopener'>Open {_e(meta['label'])}</a>"
            cards.append(f"""
            <article class='launch-card'>
              <div class='launch-top'><div><div class='kicker'>{_e(meta['label'])}</div><h3>{_e(campaign['name'])}</h3></div><div class='counts'>TRACKED</div></div>
              <p class='guidance'>{_e(guidance)}</p>
              <label>Title<input id='title-{cid}' value='{_e(title)}' readonly></label>
              <label>Post / Caption<textarea id='copy-{cid}' rows='4' readonly>{_e(copy)}</textarea></label>
              <label>CTA + Tracked Link<textarea id='cta-{cid}' rows='2' readonly>{_e(cta)}</textarea></label>
              <textarea id='full-{cid}' class='hidden-copy' readonly>{_e(full)}</textarea>
              <div class='launch-actions'>
                <button class='button' type='button' onclick="copyField('full-{cid}',this)">Copy Full Package</button>
                <button class='button secondary' type='button' onclick="sharePackage('title-{cid}','full-{cid}')">Share</button>
                {open_button}
              </div>
            </article>""")
        sections.append(f"<section class='channel-section'><div class='section-head'><div class='kicker'>Distribution lane</div><h2>{_e(meta['label'])}</h2></div>{''.join(cards)}</section>")

    body = "".join(sections) or "<div class='empty'>No active campaigns yet. Create a channel set from Demand Engine first.</div>"
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Launch Console · Empty Chair</title>
    <style>
    body{{margin:0;background:#080a08;color:#f0eadf;font-family:Inter,system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:28px}}a{{color:inherit;text-decoration:none}}h1{{font-size:44px;margin:6px 0 8px}}h2{{font-size:30px;margin:5px 0 12px}}h3{{margin:3px 0 0;font-size:21px}}.kicker{{color:#d8ff45;font:800 10px monospace;letter-spacing:.12em;text-transform:uppercase}}.note,.guidance,.empty{{color:#9ba197;font-size:12px;line-height:1.5}}.channel-section{{margin:28px 0}}.section-head{{border-bottom:1px solid #30362e;margin-bottom:12px}}.launch-card{{padding:18px;margin:12px 0;border:1px solid #30362e;background:#0e110e;box-shadow:4px 4px 0 #000}}.launch-top{{display:flex;justify-content:space-between;gap:12px}}.counts{{color:#d8ff45;font:800 10px monospace}}label{{display:block;margin-top:12px;color:#9ba197;font-size:10px;text-transform:uppercase}}input,textarea{{box-sizing:border-box;width:100%;margin-top:5px;padding:11px;border:1px solid #30362e;background:#090b09;color:#f0eadf;font:12px/1.45 Inter,system-ui,sans-serif}}.launch-actions{{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}}.button{{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:0 14px;border:1px solid #d8ff45;background:#d8ff45;color:#080a08;font-weight:900;cursor:pointer}}.button.secondary{{border-color:#3a4038;background:#171a17;color:#f0eadf}}.hidden-copy{{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}}.back{{display:inline-block;margin-bottom:10px;color:#d8ff45;font-weight:800;font-size:12px}}@media(max-width:650px){{main{{padding:18px}}h1{{font-size:36px}}.launch-card{{box-shadow:none}}.launch-actions{{display:grid}}.button{{width:100%}}}}
    </style></head><body><main><a class='back' href='/demand-acquisition'>← Demand Engine</a><div class='kicker'>Assisted multichannel distribution</div><h1>Launch Console</h1><p class='note'>Every package keeps its own tracked campaign link. Copy it, use the native Share sheet, or open the destination channel. Empty Chair does not post into third-party accounts without an authorized platform connection.</p>{body}</main>
    <script>
    async function copyField(id,button){{const field=document.getElementById(id);if(!field)return;const original=button.textContent;try{{await navigator.clipboard.writeText(field.value)}}catch(err){{field.focus();field.select();document.execCommand('copy')}}button.textContent='Copied';setTimeout(()=>button.textContent=original,1200)}}
    async function sharePackage(titleId,fullId){{const title=document.getElementById(titleId)?.value||'Tattoo inquiry';const text=document.getElementById(fullId)?.value||'';if(navigator.share){{try{{await navigator.share({{title,text}});return}}catch(err){{if(err.name==='AbortError')return}}}}try{{await navigator.clipboard.writeText(text);alert('Package copied. Paste it into the channel you want to use.')}}catch(err){{alert('Use Copy Full Package instead.')}}}}
    </script></body></html>""", headers={"Cache-Control":"no-store"})
