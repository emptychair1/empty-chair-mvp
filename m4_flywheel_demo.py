"""Cinematic automated demo of Concierge feeding M4 and Empty Chair recovery."""
import json
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
import app as core
import concierge_leads


def _ensure_demo_profile(shop_id: str):
    conn = core.connect()
    try:
        concierge_leads._ensure_table(conn)
        existing = core.db_fetchone(conn, """
            SELECT l.customer_id,l.id AS lead_id,l.profile_json,l.m4_confidence
            FROM concierge_leads l LEFT JOIN customers c ON c.id=l.customer_id
            WHERE l.shop_id=? AND c.name='Maya Carter' AND l.source='flywheel_demo'
            ORDER BY l.created_at DESC LIMIT 1
        """, (shop_id,))
        if existing:
            try:
                profile = json.loads(existing["profile_json"] or "{}")
            except Exception:
                profile = {}
            return existing["customer_id"], existing["lead_id"], profile, int(existing["m4_confidence"] or 0)
    finally:
        conn.close()

    profile = {
        "session_id": "flywheel_maya",
        "name": "Maya Carter",
        "email": "maya@example.com",
        "phone": "555-0147",
        "contact_preference": "text",
        "offer_opt_in": True,
        "project": "Bold black-and-grey botanical shoulder piece with room to extend later.",
        "styles": "black and grey, botanical, illustrative",
        "placement": "shoulder / upper arm",
        "budget": "$450-$700",
        "timing": "within 2 weeks",
        "short_notice": "yes — 24 hours is fine",
        "artist_vibe": "illustrative, patient, strong black-and-grey work",
        "travel": "up to 35 miles",
    }
    customer_id, lead_id = concierge_leads.save_concierge_profile(shop_id, profile, 95)
    conn = core.connect()
    try:
        core.db_execute(conn, "UPDATE concierge_leads SET source='flywheel_demo' WHERE id=?", (lead_id,))
        conn.commit()
    finally:
        conn.close()
    return customer_id, lead_id, profile, 95


@core.app.post("/api/m4/flywheel/seed")
def seed_flywheel(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    customer_id, lead_id, profile, confidence = _ensure_demo_profile(str(user["shop_id"]))
    return JSONResponse({"ok": True, "customer_id": customer_id, "lead_id": lead_id, "profile": profile, "confidence": confidence, "name": profile.get("name", "Maya Carter")}, headers={"Cache-Control": "no-store"})


@core.app.get("/m4-flywheel-demo", response_class=HTMLResponse)
def flywheel_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return HTMLResponse(_HTML, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Empty Chair · M4 Flywheel</title>
<link rel="stylesheet" href="/static/style.css?v=flywheel5">
<style>
:root{--b:#060806;--p:#0d100d;--p2:#111511;--i:#f2eee5;--m:#8e9689;--l:#30372f;--g:#c7ff35}
*{box-sizing:border-box}body{margin:0;background:var(--b);color:var(--i);font-family:Inter,system-ui,sans-serif}.shell{max-width:1280px;margin:auto;padding:14px 22px 90px}.top{position:sticky;top:0;z-index:30;display:flex;justify-content:space-between;align-items:center;gap:16px;padding:10px 0;background:rgba(6,8,6,.95);backdrop-filter:blur(12px);border-bottom:1px solid var(--l)}
.brand{display:flex;align-items:center;gap:12px;min-width:0}.brand img{width:128px;height:auto;display:block}.brand-fallback{display:none;font-family:'Pirata One',Georgia,serif;font-size:27px;line-height:.9}.brand-copy{font:900 10px ui-monospace,monospace;color:var(--m);letter-spacing:.13em;text-transform:uppercase}.brand-copy b{display:block;color:var(--g);margin-bottom:3px}.actions{display:flex;gap:8px}.btn{border:1px solid var(--l);background:#0b0e0b;color:var(--i);padding:10px 13px;font:400 17px 'Bangers',Impact,sans-serif;text-transform:uppercase;cursor:pointer}.btn.primary{background:var(--g);color:#071007;border-color:var(--g);box-shadow:3px 3px 0 #000}.progress{height:3px;background:#1b201b;position:sticky;top:67px;z-index:29}.progress i{display:block;height:100%;width:0;background:var(--g);transition:.5s}
.hero{padding:30px 0 44px}.card{border:1px solid var(--l);background:var(--p);box-shadow:6px 6px 0 #000;overflow:hidden}.hero-art{background:#050605}.hero-art img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover}.hero-copy{padding:26px 28px 30px;display:grid;grid-template-columns:1fr auto;gap:28px;align-items:end}.ey{color:var(--g);font:900 10px ui-monospace,monospace;letter-spacing:.15em;text-transform:uppercase}.hero h1,.stage h2,.final h2,.scene-title{font-family:'Bangers',Impact,sans-serif;font-weight:400;text-transform:uppercase}.hero h1{font-size:clamp(50px,8vw,96px);line-height:.87;margin:9px 0 13px}.hero p,.stage-nav p{color:var(--m);line-height:1.55}.hero-kicker{border:1px solid var(--l);padding:14px;min-width:210px}.hero-kicker b{display:block;color:var(--g);font:400 34px 'Bangers',Impact,sans-serif}
.stage{display:grid;grid-template-columns:210px 1fr;gap:26px;padding:40px 0;border-top:1px solid var(--l)}.stage-nav{align-self:start;position:sticky;top:95px}.stage-num{color:var(--g);font:900 10px ui-monospace,monospace;letter-spacing:.14em}.stage h2{font-size:39px;line-height:.92;margin:7px 0 9px}.stage-nav p{font-size:12px;margin:0}.scene{border:1px solid var(--l);background:var(--p);box-shadow:5px 5px 0 #000;padding:20px;overflow:hidden}.scene-title{font-size:28px;margin:0 0 12px}.listen-grid{display:grid;grid-template-columns:1.05fr .95fr;gap:16px}.listen-art img{width:100%;height:100%;min-height:330px;object-fit:cover;border:1px solid var(--l)}.chat{border:1px solid var(--l);background:#090c09;padding:15px}.bubble{border:1px solid var(--l);background:#111511;padding:12px 14px;margin:10px 0;opacity:.18;transform:translateY(12px);transition:.4s;line-height:1.45}.bubble.bot{box-shadow:inset 4px 0 0 var(--g)}.bubble.you{margin-left:14%;background:#151915}.bubble.show{opacity:1;transform:none}.bubble small{display:block;color:var(--g);font:900 9px ui-monospace,monospace;margin-bottom:5px}
.profile-card{display:grid;grid-template-columns:100px 1fr;gap:16px;align-items:center;max-width:760px;margin:26px auto;border:1px solid var(--l);background:#090c09;padding:18px;opacity:.25;transform:scale(.96);transition:.5s}.profile-card.show{opacity:1;transform:none}.profile-card img,.candidate img{object-fit:cover;border:1px solid var(--l)}.profile-card img{width:92px;height:92px}.profile-card h3{font:400 32px 'Bangers',Impact,sans-serif;margin:0}.meta{color:var(--m);font-size:11px}.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.chip{border:1px solid var(--l);padding:5px 7px;font:800 9px ui-monospace,monospace}.meter{height:7px;background:#182018;margin:12px 0 5px}.meter i{display:block;height:100%;width:30%;background:var(--g);transition:1s}.meter i.full{width:95%}
.m4-grid{display:grid;grid-template-columns:1fr 210px;gap:15px}.m4-core{border:1px solid var(--l);background:#090c09;padding:20px;display:grid;place-items:center;text-align:center;min-height:260px}.m4-core img{width:130px;height:130px;object-fit:contain}.m4-core b{font:400 41px 'Bangers',Impact,sans-serif}.signals{display:grid;gap:7px}.signal{border:1px solid var(--l);padding:10px;font:800 10px ui-monospace,monospace;color:var(--m);opacity:.25;transition:.35s}.signal.on{opacity:1;color:var(--i);border-color:var(--g);box-shadow:inset 4px 0 0 var(--g)}.candidates{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:15px}.candidate{border:1px solid var(--l);background:#090c09;padding:10px;opacity:.25;transform:translateY(10px);transition:.4s}.candidate.show{opacity:1;transform:none}.candidate.win{border-color:var(--g)}.candidate img{width:56px;height:56px}.score{color:var(--g);font:400 28px 'Bangers',Impact,sans-serif;margin-top:7px}
.phone{width:min(330px,100%);margin:20px auto;border:1px solid #495249;border-radius:28px;background:#080a08;padding:17px;opacity:.2;transform:translateY(14px);transition:.5s}.phone.show{opacity:1;transform:none}.phone-head{text-align:center;color:var(--m);font:800 9px ui-monospace,monospace;margin-bottom:100px}.sms{border:1px solid var(--l);background:#101510;padding:14px;border-radius:15px 15px 15px 4px;font-size:13px;line-height:1.5}.claim{margin-top:14px;background:var(--g);color:#071007;border-radius:999px;padding:9px;text-align:center;font-weight:900;opacity:0;transition:.35s}.claim.show{opacity:1}.outcome{display:grid;grid-template-columns:1fr 260px;gap:14px}.calendar,.revenue{border:1px solid var(--l);background:#090c09;padding:16px}.slot{height:66px;border-top:1px solid #272e27;padding:9px;color:var(--m);font:800 9px ui-monospace,monospace;position:relative}.booking{position:absolute;left:75px;right:8px;top:6px;bottom:6px;border:1px solid var(--g);background:rgba(199,255,53,.08);padding:9px;color:#ecffd0;opacity:0;transform:scaleX(.1);transform-origin:left;transition:.6s}.booking.show{opacity:1;transform:scaleX(1)}.revenue{display:grid;place-items:center;text-align:center}.revenue img{width:96px}.revenue b{display:block;color:var(--g);font:400 60px 'Bangers',Impact,sans-serif}.learn{display:grid;grid-template-columns:1fr 1fr;gap:12px}.learn-card{border:1px solid var(--l);background:#090c09;padding:16px;opacity:.25;transition:.35s}.learn-card.on{opacity:1;border-color:var(--g)}.learn-card b{display:block;font:400 27px 'Bangers',Impact,sans-serif}.learn-card span{color:var(--m);font-size:11px}.final{text-align:center;padding:65px 16px}.final h2{font-size:clamp(50px,8vw,88px);line-height:.88;margin:8px auto 16px;max-width:920px}.final p{color:var(--m);max-width:660px;margin:0 auto 22px}.status{position:fixed;left:50%;bottom:12px;transform:translateX(-50%);z-index:40;display:flex;gap:9px;align-items:center;min-width:min(610px,90vw);border:1px solid var(--l);background:rgba(7,9,7,.94);padding:9px 12px;font:800 10px ui-monospace,monospace;color:var(--m)}.dot{width:8px;height:8px;border-radius:50%;background:var(--g);box-shadow:0 0 12px var(--g)}.grow{flex:1}.status b{color:var(--g)}
@media(max-width:820px){.shell{padding:10px 14px 84px}.brand img{width:96px}.brand-copy{display:none}.actions .btn{font-size:14px;padding:8px 9px}.progress{top:59px}.hero-copy,.stage,.listen-grid,.m4-grid,.outcome,.learn{grid-template-columns:1fr}.hero-copy{padding:18px}.hero h1{font-size:52px}.hero-kicker{margin-top:15px;min-width:0}.stage{padding:28px 0}.stage-nav{position:static}.stage h2{font-size:35px}.scene{padding:14px}.listen-art img{min-height:220px}.profile-card{grid-template-columns:70px 1fr}.profile-card img{width:64px;height:64px}.candidates{grid-template-columns:repeat(2,1fr)}.hero-art img{aspect-ratio:4/3}}
</style></head><body><main class="shell">
<header class="top"><div class="brand"><img src="/static/empty-chair-logo-transparent.png?v=3" alt="Empty Chair" onerror="this.style.display='none';this.nextElementSibling.style.display='block'"><div class="brand-fallback">EMPTY<br>CHAIR</div><div class="brand-copy"><b>M4 INTELLIGENCE</b>THE FLYWHEEL DEMO</div></div><div class="actions"><button id="replay" class="btn">Replay</button><button id="start" class="btn primary">Run Demo</button></div></header><div class="progress"><i id="bar"></i></div>
<section class="hero"><article class="card"><div class="hero-art"><img src="/static/FCEFC92D-3936-4128-A229-9C4AE80B4D13.png?v=1" alt="M4 intelligence flywheel" onerror="this.onerror=null;this.src='/static/hero-demo-guide.png?v=2'"></div><div class="hero-copy"><div><div class="ey">CONCIERGE × M4 × EMPTY CHAIR</div><h1>Demand gets smarter before the chair goes empty.</h1><p>One customer signal becomes customer DNA, a ranked decision, a timely offer, a booking, recovered revenue, and stronger intelligence for the next opening.</p></div><div class="hero-kicker"><b>ONE LOOP.</b><span>Every outcome makes the next decision better.</span></div></div></article></section>
<section class="stage" id="s1"><aside class="stage-nav"><div class="stage-num">01 // LISTEN</div><h2>Concierge gets the truth.</h2><p>The interaction feels like Empty Chair—not a generic chatbot. Maya trades deliberate zero-party data for a genuinely useful experience.</p></aside><div class="scene"><div class="listen-grid"><div class="listen-art"><img src="/static/hero-concierge-leads.jpg?v=2" alt="Empty Chair Concierge"></div><div class="chat"><div class="ey">LIVE CONCIERGE // CUSTOMER ACQUISITION</div><h3 class="scene-title">RIGHT PERSON. RIGHT MESSAGE. RIGHT NOW.</h3><div class="bubble bot"><small>CONCIERGE</small>What are you actually trying to get tattooed?</div><div class="bubble you"><small>MAYA</small>Bold black-and-grey botanical work on my shoulder. I want room to extend it later.</div><div class="bubble bot"><small>CONCIERGE</small>Good. Give me budget, timing, travel radius, and whether you'd take a short-notice opening.</div><div class="bubble you"><small>MAYA</small>$450–$700. Within two weeks. About 35 miles. And yes—24 hours is fine.</div></div></div></div></section>
<section class="stage" id="s2"><aside class="stage-nav"><div class="stage-num">02 // UNDERSTAND</div><h2>Customer DNA forms.</h2><p>Declared intent becomes structured intelligence M4 can actually use.</p></aside><div class="scene"><div class="profile-card"><img src="/static/profile-10.png"><div><h3>Maya Carter</h3><div class="meta">Customer DNA · 95% confidence · zero-party + behavioral</div><div class="chips"><span class="chip">BLACK & GREY</span><span class="chip">BOTANICAL</span><span class="chip">$450–$700</span><span class="chip">≤ 35 MI</span><span class="chip">SHORT NOTICE ✓</span></div><div class="meter"><i></i></div><div class="meta">M4 confidence</div></div></div></div></section>
<section class="stage" id="s3"><aside class="stage-nav"><div class="stage-num">03 // DECIDE</div><h2>M4 finds the fit.</h2><p>Customer DNA, artist fit, practical constraints, and live availability collapse into one decision.</p></aside><div class="scene"><div class="m4-grid"><div class="m4-core"><div><img src="/static/m4-intelligence.png"><b>M4 IS THINKING.</b><div class="meta">Evidence first. Confidence attached.</div></div></div><div class="signals"><div class="signal">STYLE AFFINITY</div><div class="signal">BUDGET FIT</div><div class="signal">PLACEMENT FIT</div><div class="signal">DISTANCE</div><div class="signal">SHORT-NOTICE PROPENSITY</div></div></div><div class="candidates"><div class="candidate"><img src="/static/profile-03.png"><strong>Alex</strong><small>Traditional / illustrative</small><div class="score">74</div></div><div class="candidate win"><img src="/static/profile-06.png"><strong>Jordan</strong><small>Black & grey / botanical</small><div class="score">96</div></div><div class="candidate"><img src="/static/profile-12.png"><strong>Riley</strong><small>Fine line</small><div class="score">68</div></div><div class="candidate"><img src="/static/profile-15.png"><strong>Sam</strong><small>Neo traditional</small><div class="score">61</div></div></div></div></section>
<section class="stage" id="s4"><aside class="stage-nav"><div class="stage-num">04 // ACT</div><h2>The offer arrives.</h2><p>M4 doesn't blast the database. Empty Chair contacts the best-fit customer first.</p></aside><div class="scene"><div class="phone"><div class="phone-head">MESSAGES · EMPTY CHAIR</div><div class="sms">Hey Maya — Jordan just had a black-and-grey opening tomorrow at 2:00. Your botanical shoulder idea is a strong fit. Want first shot at it?</div><div class="claim">CLAIM OPENING</div></div></div></section>
<section class="stage" id="s5"><aside class="stage-nav"><div class="stage-num">05 // RECOVER</div><h2>The chair fills.</h2><p>The booking becomes revenue instead of dead inventory.</p></aside><div class="scene"><div class="outcome"><div class="calendar"><div class="ey">TOMORROW // JORDAN</div><div class="slot">12:00 PM</div><div class="slot">1:00 PM</div><div class="slot">2:00 PM<div class="booking">MAYA CARTER · BOTANICAL SHOULDER · CONFIRMED</div></div><div class="slot">3:00 PM</div></div><div class="revenue"><div><img src="/static/shop-avatar.png"><b>$575</b><span>RECOVERED REVENUE</span></div></div></div></div></section>
<section class="stage" id="s6"><aside class="stage-nav"><div class="stage-num">06 // LEARN</div><h2>The system remembers.</h2><p>The outcome updates the evidence behind the next decision. That's the flywheel.</p></aside><div class="scene"><div class="learn"><div class="learn-card"><b>MAYA</b><span>Short-notice responsiveness ↑<br>Jordan affinity ↑<br>Botanical confidence ↑</span></div><div class="learn-card"><b>JORDAN</b><span>Botanical conversion evidence ↑<br>$450–$700 fit strengthened<br>Shoulder placement evidence ↑</span></div><div class="learn-card"><b>SHOP</b><span>Tuesday 2 PM recovery evidence ↑<br>Offer timing evidence ↑<br>Revenue attribution written</span></div><div class="learn-card"><b>M4</b><span>Decision → intervention → outcome.<br>The next ranking starts smarter.</span></div></div></div></section>
<section class="final"><div class="ey">EMPTY CHAIR INTELLIGENCE</div><h2>Every filled chair teaches M4 how to fill the next one.</h2><p>This is more than recovery automation. It is a compounding intelligence layer built from customer truth, practical fit, attribution, and outcomes.</p><button class="btn primary" onclick="runDemo()">Run It Again</button></section>
</main><div class="status"><span class="dot"></span><span id="status">READY</span><span class="grow"></span><b id="pct">0%</b></div>
<script>
const sleep=ms=>new Promise(r=>setTimeout(r,ms));const qs=s=>document.querySelector(s),qsa=s=>[...document.querySelectorAll(s)];let running=false;
function reset(){qsa('.show,.on,.full').forEach(x=>x.classList.remove('show','on','full'));qs('#bar').style.width='0';qs('#pct').textContent='0%';qs('#status').textContent='READY'}
function progress(n,t){qs('#bar').style.width=n+'%';qs('#pct').textContent=n+'%';qs('#status').textContent=t}
async function runDemo(){if(running)return;running=true;reset();progress(5,'CONCIERGE IS LISTENING');for(const b of qsa('#s1 .bubble')){await sleep(420);b.classList.add('show')}progress(20,'CUSTOMER DNA WRITTEN');try{await fetch('/api/m4/flywheel/seed',{method:'POST'})}catch(e){}qs('#s2 .profile-card').classList.add('show');await sleep(450);qs('#s2 .meter i').classList.add('full');await sleep(600);progress(42,'M4 IS EVALUATING EVIDENCE');for(const s of qsa('.signal')){await sleep(180);s.classList.add('on')}for(const c of qsa('.candidate')){await sleep(180);c.classList.add('show')}await sleep(650);progress(64,'BEST MATCH FOUND · JORDAN 96');qs('.phone').classList.add('show');await sleep(700);qs('.claim').classList.add('show');await sleep(700);progress(80,'MAYA CLAIMED THE OPENING');qs('.booking').classList.add('show');await sleep(700);progress(92,'$575 RECOVERED');for(const l of qsa('.learn-card')){await sleep(260);l.classList.add('on')}progress(100,'OUTCOME WRITTEN · M4 LEARNED');running=false}
qs('#start').onclick=runDemo;qs('#replay').onclick=runDemo;setTimeout(runDemo,700);
</script></body></html>'''
