"""Read-only Marketplace copy preflight and launch packages for demand acquisition campaigns.

This module intentionally makes no database schema changes. It provides a
conservative copy review plus ready-to-copy launch materials for signed-in
shops. It does not guarantee approval and does not attempt moderation evasion.
"""
import html
import re
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core


META_COMMERCE_POLICY_URL = "https://www.facebook.com/policies_center/commerce"


def _e(value):
    return html.escape(str(value or ""), quote=True)


def marketplace_copy_guard(title, copy):
    """Return heuristic status and findings without persisting anything."""
    text = f"{title} {copy}".lower()
    findings = []
    severity = 0

    red_rules = [
        (r"\bguaranteed\b|\bguarantee\b", "Remove guarantee or guaranteed-outcome language."),
        (r"\bfree tattoo\b", "Review any free-tattoo claim for accuracy and platform eligibility."),
        (r"\bno id\b|\bunder 18\b|\bminor\b", "Age or ID language requires manual legal and policy review."),
        (r"\bvenmo\b|\bcashapp\b|\bzelle\b", "Keep direct payment-handle instructions out of discovery copy."),
    ]
    yellow_rules = [
        (r"https?://|www\.", "External-link language should only be used where the channel currently permits it."),
        (r"\bdeposit\b|\bpay now\b", "Move transaction language to the booking flow rather than discovery copy."),
        (r"!!!+|\$\$\$+", "Reduce spam-like punctuation."),
        (r"\burgent\b|\blast chance\b|\bact now\b", "Avoid pressure-heavy language that can read as spammy."),
    ]

    for pattern, note in red_rules:
        if re.search(pattern, text):
            severity = max(severity, 2)
            findings.append(note)
    for pattern, note in yellow_rules:
        if re.search(pattern, text):
            severity = max(severity, 1)
            findings.append(note)

    if len(copy.strip()) < 35:
        severity = max(severity, 1)
        findings.append("Add enough truthful context for a buyer to understand the offer.")

    if severity == 2:
        status = "red"
        label = "DO NOT POST YET"
    elif severity == 1:
        status = "yellow"
        label = "REVIEW COPY"
    else:
        status = "green"
        label = "COPY PASS"
        findings.append("No local copy-risk rules triggered. Platform/category eligibility still requires current Meta policy review.")

    return status, label, findings


def _draft_copy(campaign):
    artist = campaign["artist_name"] or "the artist"
    studio = campaign["studio_name"] or "the studio"
    hook = campaign["hook"] or campaign["name"]
    title = f"{campaign['name']} — Athens"
    copy = (
        f"{hook}. Work by {artist}, currently tattooing at {studio} in Athens. "
        "Send your idea, placement, approximate size, budget and timing through Tattoo Concierge to see if it is a fit."
    )
    return title, copy


def _tracked_url(request, campaign):
    base = str(request.base_url).rstrip("/")
    params = urlencode(
        {
            "shop_id": campaign["shop_id"],
            "campaign_id": campaign["id"],
            "src": campaign["channel"],
        }
    )
    return f"{base}/a/{campaign['id']}?{params}"


@core.app.get("/demand-acquisition/compliance", response_class=HTMLResponse)
def demand_acquisition_compliance(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        campaigns = core.db_fetchall(
            conn,
            """SELECT c.*, i.artist_name, i.studio_name
               FROM acquisition_campaigns c
               LEFT JOIN acquisition_identities i ON i.id=c.identity_id
               WHERE c.shop_id=?
               ORDER BY c.created_at DESC""",
            (user["shop_id"],),
        )
    except Exception:
        conn.rollback()
        campaigns = []
    finally:
        conn.close()

    cards = []
    for campaign in campaigns:
        title, copy = _draft_copy(campaign)
        status, label, findings = marketplace_copy_guard(title, copy)
        tracked_url = _tracked_url(request, campaign)
        package = f"{title}\n\n{copy}\n\n{tracked_url}"
        finding_html = "".join(f"<li>{_e(item)}</li>" for item in findings)
        campaign_id = _e(campaign["id"])
        button_disabled = " disabled" if status == "red" else ""
        button_label = "Fix copy before posting" if status == "red" else "Copy full launch package"
        cards.append(
            f"""<article class='campaign'>
            <div class='top'><b>{_e(campaign['name'])}</b><span class='{_e(status)}'>{_e(label)}</span></div>
            <div class='owner'>{_e(campaign['artist_name'] or 'Artist')} @ {_e(campaign['studio_name'] or 'Independent')} · {_e(campaign['channel'])}</div>

            <label>MARKETPLACE TITLE</label>
            <div class='copyrow'><textarea id='title-{campaign_id}' readonly>{_e(title)}</textarea><button type='button' class='secondary' onclick="copyField('title-{campaign_id}', this)">Copy title</button></div>

            <label>MARKETPLACE DESCRIPTION</label>
            <div class='copyrow'><textarea id='copy-{campaign_id}' rows='5' readonly>{_e(copy)}</textarea><button type='button' class='secondary' onclick="copyField('copy-{campaign_id}', this)">Copy description</button></div>

            <label>TRACKED CONCIERGE LINK</label>
            <div class='copyrow'><textarea id='link-{campaign_id}' readonly>{_e(tracked_url)}</textarea><button type='button' class='secondary' onclick="copyField('link-{campaign_id}', this)">Copy link</button></div>

            <label>COMPLIANCE RESULT</label>
            <ul>{finding_html}</ul>

            <textarea id='package-{campaign_id}' class='hidden-copy' readonly>{_e(package)}</textarea>
            <button type='button' class='primary' onclick="copyField('package-{campaign_id}', this)"{button_disabled}>{_e(button_label)}</button>
            </article>"""
        )

    body = "".join(cards) or "<p class='empty'>No campaigns yet. Create the five starter campaigns first.</p>"
    return HTMLResponse(
        f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
        <title>Launch Packages · Empty Chair</title><style>
        body{{margin:0;background:#080a08;color:#f0eadf;font-family:Inter,system-ui,sans-serif}}
        main{{max-width:1000px;margin:auto;padding:30px}}h1{{font-size:40px;margin:7px 0 10px}}
        .ey{{color:#d8ff45;font:700 11px monospace;letter-spacing:.15em}}a{{color:#d8ff45}}
        article{{border:1px solid #30362e;background:#0e110e;padding:18px;margin:14px 0}}
        .top span{{float:right;font:800 11px monospace;letter-spacing:.08em}}.green{{color:#d8ff45}}.yellow{{color:#ffd45b}}.red{{color:#ff6961}}
        .owner,.note,.empty{{color:#9ba197;font-size:13px}}label{{display:block;color:#9ba197;font-size:11px;margin-top:14px}}
        textarea{{box-sizing:border-box;width:100%;margin-top:5px;border:1px solid #30362e;background:#090b09;color:#f0eadf;padding:12px;line-height:1.45;resize:vertical}}
        .copyrow{{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:start}}
        button{{border:0;font-weight:900;cursor:pointer}}button.secondary{{margin-top:5px;padding:12px 14px;background:#242924;color:#f0eadf;white-space:nowrap}}
        button.primary{{margin-top:15px;padding:13px 18px;background:#d8ff45;color:#080a08}}button:disabled{{cursor:not-allowed;opacity:.45}}
        li{{margin:6px 0;color:#c7ccc3}}.policy{{margin:20px 0;padding:14px;border-left:3px solid #d8ff45;background:#0e110e}}
        .hidden-copy{{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}}
        @media(max-width:650px){{.copyrow{{grid-template-columns:1fr}}button.secondary{{width:100%}}}}
        </style></head><body><main>
        <a href='/demand-acquisition'>← Demand Acquisition</a>
        <div class='ey'>M4 · READY-TO-POST DEMAND</div><h1>Marketplace Launch Packages</h1>
        <p class='note'>Each campaign below contains the exact title, description and tracked Concierge link needed for launch. Copy the full package or each field separately.</p>
        <div class='policy'><b>Preflight only.</b> Green means the local copy rules found no obvious issue; it does not mean Meta has approved the listing or that the listing category is eligible. <a href='{META_COMMERCE_POLICY_URL}' target='_blank' rel='noopener'>Review Meta Commerce Policies</a>.</div>
        {body}
        </main>
        <script>
        async function copyField(id, button) {{
          const field = document.getElementById(id);
          if (!field || button.disabled) return;
          const original = button.textContent;
          try {{
            await navigator.clipboard.writeText(field.value);
            button.textContent = 'Copied';
          }} catch (err) {{
            field.focus();
            field.select();
            document.execCommand('copy');
            button.textContent = 'Copied';
          }}
          window.setTimeout(() => {{ button.textContent = original; }}, 1400);
        }}
        </script></body></html>""",
        headers={"Cache-Control": "no-store"},
    )
