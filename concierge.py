"""Empty Chair Concierge: customer-side zero-party intelligence experience."""
import uuid
from fastapi import Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
import app as core
import concierge_leads

DEMO_SHOP_ID = "shop_live_demo"


def _profile_score(p):
    fields = ["styles", "placement", "budget", "timing", "short_notice", "artist_vibe", "travel", "project"]
    known = sum(bool(p.get(k)) for k in fields)
    return round(25 + 70 * known / len(fields))


@core.app.post("/api/concierge/profile")
def concierge_profile(
    request: Request,
    shop_id: str = Form(""),
    session_id: str = Form(""),
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(...),
    contact_preference: str = Form(""),
    offer_consent: str = Form(...),
    project: str = Form(""),
    styles: str = Form(""),
    placement: str = Form(""),
    budget: str = Form(""),
    timing: str = Form(""),
    short_notice: str = Form(""),
    artist_vibe: str = Form(""),
    travel: str = Form(""),
):
    sid = session_id.strip() or f"conc_{uuid.uuid4().hex[:12]}"
    target_shop = shop_id.strip() or DEMO_SHOP_ID
    p = {
        "session_id": sid,
        "name": name.strip(),
        "email": email.strip(),
        "phone": phone.strip(),
        "contact_preference": contact_preference.strip(),
        "offer_opt_in": offer_consent == "yes",
        "project": project.strip(),
        "styles": styles.strip(),
        "placement": placement.strip(),
        "budget": budget.strip(),
        "timing": timing.strip(),
        "short_notice": short_notice.strip(),
        "artist_vibe": artist_vibe.strip(),
        "travel": travel.strip(),
    }
    if not p["name"] or not p["phone"]:
        return JSONResponse({"error": "Name and phone are required to create your profile."}, status_code=400)
    before = 31
    after = _profile_score(p)
    try:
        customer_id, lead_id = concierge_leads.save_concierge_profile(target_shop, p, after)
    except Exception as exc:
        return JSONResponse({"error": f"Could not save customer profile: {exc}"}, status_code=500)
    signals = [{"label": k.replace("_", " ").title(), "value": v} for k, v in p.items() if k not in {"session_id", "email", "phone", "offer_opt_in"} and v]
    return JSONResponse({
        "ok": True,
        "session_id": sid,
        "customer_id": customer_id,
        "lead_id": lead_id,
        "profile_created": True,
        "communication_consent": p["offer_opt_in"],
        "signals": signals,
        "m4_confidence_before": before,
        "m4_confidence_after": after,
        "value": {
            "name": p["name"],
            "readiness": "ready to match" if after >= 70 else "developing",
            "short_notice": p.get("short_notice") or "not specified",
            "budget": p.get("budget") or "not specified",
            "style": p.get("styles") or "open",
            "contact_preference": p.get("contact_preference") or "not specified",
        },
    }, headers={"Cache-Control": "no-store"})


@core.app.get("/concierge", response_class=HTMLResponse)
def concierge_page(request: Request):
    shop_id = (request.query_params.get("shop_id") or DEMO_SHOP_ID).replace('"', '')
    return HTMLResponse(f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Empty Chair Concierge</title><style>
:root{{--g:#a6ff2e;--bg:#070907;--p:#0d110d;--line:#273027;--ink:#edf4e9;--muted:#899386}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 50% -10%,rgba(166,255,46,.08),transparent 35%),var(--bg);color:var(--ink);font-family:Inter,system-ui,sans-serif}}.wrap{{max-width:1040px;margin:auto;padding:28px}}.brand{{font-weight:900;letter-spacing:.16em;border-bottom:1px solid var(--line);padding-bottom:18px}}.hero{{padding:56px 0 30px}}.ey{{font:700 10px ui-monospace,monospace;color:var(--g);letter-spacing:.14em;text-transform:uppercase}}.hero h1{{font-size:clamp(44px,7vw,78px);line-height:.94;letter-spacing:-.055em;margin:10px 0 16px}}.hero p{{color:#a7afa3;line-height:1.65;max-width:700px}}.grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:16px}}.card{{border:1px solid var(--line);background:var(--p);padding:22px}}.section{{border-bottom:1px solid var(--line);padding-bottom:8px;margin:4px 0 18px}}.q{{margin-bottom:18px}}.q label{{display:block;font-size:11px;font-weight:800;margin-bottom:7px}}.q input,.q textarea,.q select{{width:100%;background:#080b08;border:1px solid #334033;color:var(--ink);padding:12px;font:inherit}}.q textarea{{min-height:76px}}.radio{{display:grid;gap:8px;border:1px solid #334033;padding:12px}}.radio label{{display:flex;gap:9px;align-items:flex-start;font-weight:500;line-height:1.45}}.radio input{{width:auto;margin-top:3px}}.btn{{width:100%;padding:14px;background:var(--g);border:0;color:#081007;font-weight:900;letter-spacing:.08em;text-transform:uppercase;cursor:pointer}}.cell{{width:54px;height:54px;margin:10px 0 24px;border-radius:47% 53% 44% 56%;background:rgba(166,255,46,.15);box-shadow:0 0 30px rgba(166,255,46,.45);animation:b 3s ease-in-out infinite}}@keyframes b{{50%{{transform:scale(1.14) rotate(7deg)}}}}.meter{{height:8px;background:#161d16;margin:9px 0 5px}}.meter i{{display:block;height:100%;background:var(--g);width:31%;transition:1s}}.signals{{display:grid;gap:7px;margin-top:14px}}.sig{{border:1px solid #303b30;padding:10px}}.sig b{{font-size:10px;color:var(--g);text-transform:uppercase}}.sig span{{display:block;color:#b6bfb1;font-size:12px;margin-top:4px}}.result{{display:none}}.gift{{margin-top:18px;border-left:2px solid var(--g);padding:14px;background:#10160f}}.gift strong{{display:block;font-size:18px;margin-bottom:8px}}.gift div{{font-size:12px;color:#b6c0b2;line-height:1.7}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}.wrap{{padding:18px}}}}</style></head><body><div class="wrap"><div class="brand">EMPTY CHAIR <span style="color:var(--g)">/ CONCIERGE</span></div><section class="hero"><div class="ey">A useful profile, not a lead form</div><h1>Know what you want. Be easier to match.</h1><p>Build a tattoo profile you can actually use. If you choose to opt in, Empty Chair can also use these preferences to surface unusually good openings instead of generic blasts.</p></section><div class="grid"><div class="card"><form id="f"><input type="hidden" name="shop_id" value="{shop_id}"><div class="section"><div class="ey">01 / Who you are</div></div><div class="q"><label>Name *</label><input name="name" required autocomplete="name"></div><div class="q"><label>Phone *</label><input name="phone" required autocomplete="tel" inputmode="tel"></div><div class="q"><label>Email</label><input name="email" type="email" autocomplete="email"></div><div class="q"><label>Best way to reach you</label><select name="contact_preference"><option value="">Choose</option><option>Text</option><option>Email</option><option>Either</option></select></div><div class="section"><div class="ey">02 / Your tattoo profile</div></div><div class="q"><label>What are you thinking about getting?</label><textarea name="project" placeholder="A black panther on my thigh, maybe palm-sized…"></textarea></div><div class="q"><label>Styles you actually like</label><input name="styles" placeholder="American traditional, blackwork, fine line…"></div><div class="q"><label>Placement</label><input name="placement" placeholder="Forearm, thigh, ribs…"></div><div class="q"><label>Comfortable budget</label><select name="budget"><option value="">Choose</option><option>$150–300</option><option>$300–600</option><option>$600–1,000</option><option>$1,000+</option></select></div><div class="q"><label>When do you want it?</label><select name="timing"><option value="">Choose</option><option>As soon as possible</option><option>Next 30 days</option><option>Next 3 months</option><option>Just exploring</option></select></div><div class="q"><label>If a great artist had a cancellation tomorrow?</label><select name="short_notice"><option value="">Choose</option><option>Text me — I can move fast</option><option>Maybe, with 2–3 days notice</option><option>I need to plan ahead</option></select></div><div class="q"><label>What matters in an artist?</label><input name="artist_vibe" placeholder="Traditional specialist, collaborative, quiet appointment…"></div><div class="q"><label>How far would you travel?</label><select name="travel"><option value="">Choose</option><option>15 miles</option><option>30 miles</option><option>60 miles</option><option>Worth traveling for the right artist</option></select></div><div class="section"><div class="ey">03 / Your permission</div></div><div class="q"><label>May Empty Chair contact you about tattoo openings that match this profile? *</label><div class="radio"><label><input type="radio" name="offer_consent" value="yes" required> Yes — send me relevant tattoo-opening opportunities using my selected contact method.</label><label><input type="radio" name="offer_consent" value="no" required> No — create my profile, but do not contact me with opening offers.</label></div></div><button class="btn">Create my customer profile</button></form></div><aside class="card"><div class="cell"></div><div class="ey">M4 signal visibility</div><h2>What changes when you tell us.</h2><p style="color:var(--muted);font-size:12px;line-height:1.6">Your identity and profile are stored as a customer profile. Contact permission is stored separately and only becomes active if you explicitly choose Yes.</p><div style="font-size:11px">M4 confidence <b id="pct">31%</b></div><div class="meter"><i id="bar"></i></div><div id="result" class="result"><div id="signals" class="signals"></div><div class="gift"><strong>Your customer profile is created</strong><div id="gift"></div></div></div></aside></div></div><script>const f=document.getElementById('f');f.onsubmit=async e=>{{e.preventDefault();const r=await fetch('/api/concierge/profile',{{method:'POST',body:new FormData(f),cache:'no-store'}}),j=await r.json();if(!r.ok){{alert(j.error||'Could not create profile');return}}document.getElementById('pct').textContent=j.m4_confidence_after+'%';document.getElementById('bar').style.width=j.m4_confidence_after+'%';const s=document.getElementById('signals');s.innerHTML='';j.signals.forEach(x=>s.innerHTML+=`<div class="sig"><b>${{x.label}}</b><span>${{x.value}}</span></div>`);document.getElementById('gift').innerHTML=`Customer: ${{j.value.name}}<br>Style: ${{j.value.style}}<br>Budget: ${{j.value.budget}}<br>Short-notice: ${{j.value.short_notice}}<br>Preferred contact: ${{j.value.contact_preference}}<br>Offer consent: ${{j.communication_consent?'YES':'NO'}}<br><br><b style="color:var(--g)">Customer ID: ${{j.customer_id}}</b><br>M4 gained ${{j.m4_confidence_after-j.m4_confidence_before}} confidence points from the profile.`;document.getElementById('result').style.display='block';document.getElementById('result').scrollIntoView({{behavior:'smooth'}})}};</script></body></html>''', headers={{"Cache-Control":"no-store"}})
