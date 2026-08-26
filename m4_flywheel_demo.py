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
    return JSONResponse(
        {
            "ok": True,
            "customer_id": customer_id,
            "lead_id": lead_id,
            "profile": profile,
            "confidence": confidence,
            "name": profile.get("name", "Maya Carter"),
        },
        headers={"Cache-Control": "no-store"},
    )


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
<link rel="stylesheet" href="/static/style.css?v=flywheel3">
<style>
:root{--black:#060806;--panel:#0d100d;--panel2:#111511;--cream:#f2eee5;--muted:#8e9689;--line:#30372f;--lime:#c7ff35;--shadow:#000}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--black);color:var(--cream);font-family:Inter,system-ui,sans-serif;overflow-x:hidden}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background:radial-gradient(circle at 70% 8%,rgba(199,255,53,.07),transparent 34%);z-index:-1}
.shell{max-width:1280px;margin:auto;padding:18px 24px 96px}.top{position:sticky;top:0;z-index:30;display:flex;align-items:center;justify-content:space-between;gap:18px;padding:12px 0;background:rgba(6,8,6,.92);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:14px;min-width:0}.brand img{width:126px;height:auto;display:block}.brand-copy{font:900 10px ui-monospace,monospace;letter-spacing:.16em;color:var(--muted);text-transform:uppercase}.brand-copy b{display:block;color:var(--lime);font-size:11px;margin-bottom:4px}.actions{display:flex;gap:8px}.btn{appearance:none;border:1px solid var(--line);background:#0b0e0b;color:var(--cream);padding:11px 14px;font-family:'Bangers',Impact,sans-serif;font-size:18px;letter-spacing:.03em;text-transform:uppercase;cursor:pointer}.btn.primary{background:var(--lime);color:#071007;border-color:var(--lime);box-shadow:3px 3px 0 #000}.progress{height:3px;background:#1b201b;position:sticky;top:73px;z-index:29}.progress i{display:block;width:0;height:100%;background:var(--lime);box-shadow:0 0 16px rgba(199,255,53,.65);transition:width .55s ease}
.hero{padding:34px 0 46px}.hero-card{border:1px solid var(--line);background:var(--panel);box-shadow:7px 7px 0 #000;overflow:hidden}.hero-art{position:relative;background:#050605}.hero-art img{display:block;width:100%;height:auto;aspect-ratio:16/9;object-fit:cover}.hero-art:after{content:"";position:absolute;inset:auto 0 0;height:28%;background:linear-gradient(transparent,rgba(5,6,5,.95))}.hero-copy{padding:28px 30px 32px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:30px;align-items:end}.ey{color:var(--lime);font:900 11px ui-monospace,monospace;letter-spacing:.16em;text-transform:uppercase}.hero h1,.stage h2,.final h2{font-family:'Bangers',Impact,sans-serif;font-weight:400;text-transform:uppercase}.hero h1{font-size:clamp(54px,8vw,104px);line-height:.86;letter-spacing:.01em;margin:10px 0 14px;max-width:940px}.hero p{max-width:760px;color:var(--muted);font-size:17px;line-height:1.6;margin:0}.hero-kicker{border:1px solid var(--line);padding:16px;min-width:220px;background:#090c09}.hero-kicker b{display:block;color:var(--lime);font:400 38px 'Bangers',Impact,sans-serif}.hero-kicker span{font:800 9px ui-monospace,monospace;color:var(--muted);letter-spacing:.12em;text-transform:uppercase}
.stage{display:grid;grid-template-columns:220px minmax(0,1fr);gap:28px;padding:44px 0;border-top:1px solid var(--line)}.stage-nav{align-self:start;position:sticky;top:102px}.stage-num{font:900 11px ui-monospace,monospace;color:var(--lime);letter-spacing:.15em}.stage h2{font-size:42px;line-height:.92;margin:8px 0 10px}.stage-nav p{color:var(--muted);font-size:12px;line-height:1.55;margin:0}.scene{border:1px solid var(--line);background:var(--panel);box-shadow:5px 5px 0 #000;padding:24px;min-height:390px;position:relative;overflow:hidden}.scene:before{content:"";position:absolute;inset:0;pointer-events:none;background:radial-gradient(circle at 82% 10%,rgba(199,255,53,.06),transparent 32%)}
.chat{max-width:760px;margin:auto}.bubble{max-width:78%;border:1px solid var(--line);background:#111511;padding:14px 16px;margin:12px 0;opacity:.18;transform:translateY(14px);transition:.45s}.bubble.bot{box-shadow:inset 4px 0 0 var(--lime)}.bubble.you{margin-left:auto}.bubble.show{opacity:1;transform:none}.bubble small{display:block;color:var(--lime);font:900 9px ui-monospace,monospace;letter-spacing:.12em;margin-bottom:6px}
.profile-card{display:grid;grid-template-columns:108px 1fr;gap:18px;align-items:center;max-width:780px;margin:34px auto;border:1px solid var(--line);background:#0a0d0a;padding:20px;opacity:.25;transform:scale(.96);transition:.55s}.profile-card.show{opacity:1;transform:none}.profile-card img{width:96px;height:96px;object-fit:cover;border:1px solid var(--line);background:#080a08}.profile-card h3{font-family:'Bangers',Impact,sans-serif;font-size:34px;font-weight:400;margin:0 0 4px}.meta{color:var(--muted);font-size:11px;line-height:1.5}.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}.chip{border:1px solid var(--line);padding:6px 8px;font:800 9px ui-monospace,monospace;color:#c5c9c1}.meter{height:8px;background:#192019;margin:14px 0 5px}.meter i{display:block;height:100%;width:30%;background:var(--lime);transition:width 1s}.meter i.full{width:95%}
.m4-grid{display:grid;grid-template-columns:1fr 220px;gap:18px;align-items:center}.m4-core{border:1px solid var(--line);background:#080b08;padding:24px;min-height:260px;display:grid;place-items:center;text-align:center}.m4-core .robot{width:128px;height:128px;object-fit:contain;margin-bottom:10px}.m4-core b{display:block;font-family:'Bangers',Impact,sans-serif;font-size:44px;font-weight:400}.signal-list{display:grid;gap:8px}.signal{border:1px solid var(--line);padding:11px 12px;font:800 10px ui-monospace,monospace;color:var(--muted);opacity:.25;transition:.35s}.signal.on{opacity:1;color:var(--cream);border-color:var(--lime);box-shadow:inset 4px 0 0 var(--lime)}
.candidates{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:18px}.candidate{border:1px solid var(--line);background:#0a0d0a;padding:12px;opacity:.25;transform:translateY(12px);transition:.4s}.candidate.show{opacity:1;transform:none}.candidate.win{border-color:var(--lime);box-shadow:0 0 24px rgba(199,255,53,.1)}.candidate img{width:58px;height:58px;object-fit:cover;border:1px solid var(--line);display:block;margin-bottom:9px}.candidate strong{font-size:13px}.candidate small{display:block;color:var(--muted);font-size:9px;margin-top:5px}.score{color:var(--lime);font:400 29px 'Bangers',Impact,sans-serif;margin-top:8px}
.phone{width:min(330px,100%);margin:24px auto;border:1px solid #485247;border-radius:28px;background:#080a08;padding:18px;box-shadow:0 28px 70px #000;opacity:.2;transform:translateY(16px);transition:.55s}.phone.show{opacity:1;transform:none}.phone-head{text-align:center;color:var(--muted);font:800 9px ui-monospace,monospace;margin-bottom:120px}.sms{border:1px solid var(--line);background:#101510;padding:15px;border-radius:16px 16px 16px 4px;font-size:13px;line-height:1.55}.claim{margin-top:16px;background:var(--lime);color:#081007;border-radius:999px;text-align:center;padding:10px;font-weight:900;opacity:0;transform:scale(.9);transition:.4s}.claim.show{opacity:1;transform:none}
.outcome{display:grid;grid-template-columns:1fr 280px;gap:16px}.calendar,.revenue{border:1px solid var(--line);background:#090c09;padding:18px}.slot{height:72px;border-top:1px solid #262d26;padding:10px;color:var(--muted);font:800 9px ui-monospace,monospace;position:relative}.booking{position:absolute;left:82px;right:10px;top:7px;bottom:7px;border:1px solid var(--lime);background:rgba(199,255,53,.08);padding:10px;color:#ecffd0;opacity:0;transform:scaleX(.1);transform-origin:left;transition:.65s}.booking.show{opacity:1;transform:scaleX(1)}.revenue{display:grid;place-items:center;text-align:center}.revenue img{width:92px;height:auto}.revenue b{display:block;color:var(--lime);font:400 64px 'Bangers',Impact,sans-serif}.revenue span{color:var(--muted);font-size:11px}.learn{display:grid;grid-template-columns:1fr 1fr;gap:14px}.learn-card{border:1px solid var(--line);background:#090c09;padding:18px;opacity:.25;transition:.4s}.learn-card.on{opacity:1;border-color:var(--lime)}.learn-card b{display:block;font-family:'Bangers',Impact,sans-serif;font-size:28px;font-weight:400}.learn-card span{color:var(--muted);font-size:11px;line-height:1.5}.final{text-align:center;padding:74px 18px 20px}.final h2{font-size:clamp(52px,8vw,98px);line-height:.86;margin:8px auto 18px;max-width:980px}.final p{max-width:700px;margin:0 auto 24px;color:var(--muted);line-height:1.6}.status{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:40;display:flex;align-items:center;gap:10px;min-width:min(620px,90vw);border:1px solid var(--line);background:rgba(7,9,7,.94);padding:10px 13px;backdrop-filter:blur(12px);font:800 10px ui-monospace,monospace;color:var(--muted)}.dot{width:8px;height:8px;border-radius:50%;background:var(--lime);box-shadow:0 0 12px var(--lime)}.status b{color:var(--lime)}.grow{flex:1}
@media(max-width:820px){.shell{padding:10px 14px 90px}.brand img{width:100px}.brand-copy{display:none}.actions .btn{font-size:15px;padding:9px 10px}.progress{top:61px}.hero{padding-top:22px}.hero-copy{display:block;padding:18px}.hero h1{font-size:54px}.hero p{font-size:14px}.hero-kicker{margin-top:18px;min-width:0}.stage{grid-template-columns:1fr;padding:30px 0}.stage-nav{position:static}.stage h2{font-size:36px}.scene{padding:15px;min-height:0}.profile-card{grid-template-columns:72px 1fr;padding:14px}.profile-card img{width:66px;height:66px}.m4-grid,.outcome,.learn{grid-template-columns:1fr}.candidates{grid-template-columns:repeat(2,1fr)}.status{bottom:8px}.hero-art img{aspect-ratio:4/3;object-position:center}}
</style>
</head>
<body>
<main class="shell">
<header class="top">
  <div class="brand"><img src="/static/empty-chair-logo-transparent.png" alt="Empty Chair"><div class="brand-copy"><b>M4 INTELLIGENCE</b>THE FLYWHEEL DEMO</div></div>
  <div class="actions"><button id="replay" class="btn">Replay</button><button id="start" class="btn primary">Run Demo</button></div>
</header>
<div class="progress"><i id="bar"></i></div>

<section class="hero">
  <article class="hero-card">
    <div class="hero-art"><img src="/static/m4-flywheel-hero.png?v=1" alt="M4 intelligence flywheel inside the Empty Chair universe"></div>
    <div class="hero-copy">
      <div><div class="ey">CONCIERGE × M4 × EMPTY CHAIR</div><h1>Demand gets smarter before the chair goes empty.</h1><p>Watch one customer signal move through Concierge, customer DNA, M4 matching, an open chair, a booking, recovered revenue, and back into the intelligence layer.</p></div>
      <div class="hero-kicker"><b>ONE LOOP.</b><span>Every outcome makes the next decision better.</span></div>
    </div>
  </article>
</section>

<section class="stage" id="s1"><aside class="stage-nav"><div class="stage-num">01 // LISTEN</div><h2>Concierge gets the truth.</h2><p>Maya deliberately tells Empty Chair what she wants, what she can spend, and when she can move.</p></aside><div class="scene"><div class="chat"><div class="bubble bot"><small>CONCIERGE</small>What are you actually trying to get tattooed?</div><div class="bubble you"><small>MAYA</small>Bold black-and-grey botanical work on my shoulder. I want room to extend it later.</div><div class="bubble bot"><small>CONCIERGE</small>Budget and timing?</div><div class="bubble you"><small>MAYA</small>$450–700. Within two weeks. And yes, I can do short notice.</div></div></div></section>

<section class="stage" id="s2"><aside class="stage-nav"><div class="stage-num">02 // UNDERSTAND</div><h2>Signal becomes customer DNA.</h2><p>The conversation stops being disposable. It becomes durable evidence M4 can reason from.</p></aside><div class="scene"><div class="profile-card" id="profile"><img src="/static/profile-10.png" alt="Maya Carter"><div><div class="ey">CUSTOMER DNA</div><h3>Maya Carter</h3><div class="meta">Black & grey · Botanical · Shoulder / upper arm · $450–700 · Short notice OK</div><div class="chips"><span class="chip">Consent YES</span><span class="chip">Within 2 weeks</span><span class="chip">35 mile travel</span><span class="chip">Illustrative artist fit</span></div><div class="meter"><i id="meter"></i></div><div class="meta">Profile confidence <b id="confidence">31%</b></div></div></div></div></section>

<section class="stage" id="s3"><aside class="stage-nav"><div class="stage-num">03 // DECIDE</div><h2>M4 does the decision work.</h2><p>Style, artist fit, timing, history, readiness and practical constraints become one ranked decision.</p></aside><div class="scene"><div class="m4-grid"><div class="m4-core"><div><img class="robot" src="/static/m4-intelligence.png" alt="M4"><b>M4 INTELLIGENCE</b><div class="meta">Observe → compare → choose → learn</div></div></div><div class="signal-list"><div class="signal">STYLE FIT</div><div class="signal">ARTIST FIT</div><div class="signal">TIME FIT</div><div class="signal">BUDGET FIT</div><div class="signal">READINESS</div><div class="signal">OUTCOME HISTORY</div></div></div><div class="candidates"><div class="candidate"><img src="/static/profile-03.png" alt="Jordan"><strong>Jordan</strong><small>Black & grey · available</small><div class="score">94</div></div><div class="candidate"><img src="/static/profile-06.png" alt="Alex"><strong>Alex</strong><small>Traditional · available</small><div class="score">71</div></div><div class="candidate"><img src="/static/profile-12.png" alt="Sam"><strong>Sam</strong><small>Illustrative · booked</small><div class="score">63</div></div><div class="candidate"><img src="/static/profile-15.png" alt="Riley"><strong>Riley</strong><small>Fine line · available</small><div class="score">48</div></div></div></div></section>

<section class="stage" id="s4"><aside class="stage-nav"><div class="stage-num">04 // ACT</div><h2>The right offer reaches the right person.</h2><p>M4 does not blast the list. It uses the strongest fit first.</p></aside><div class="scene"><div class="phone" id="phone"><div class="phone-head">EMPTY CHAIR · MESSAGE</div><div class="sms">Hey Maya — Jordan has a short-notice opening Saturday at 3:00 PM. It fits the black-and-grey botanical project you told us about. Want it?</div><div class="claim" id="claim">CLAIM OPENING</div></div></div></section>

<section class="stage" id="s5"><aside class="stage-nav"><div class="stage-num">05 // OUTCOME</div><h2>The empty chair becomes real revenue.</h2><p>The booking and the money are measured outcomes, not optimistic attribution.</p></aside><div class="scene"><div class="outcome"><div class="calendar"><div class="ey">SATURDAY</div><div class="slot">1:00 PM</div><div class="slot">2:00 PM</div><div class="slot">3:00 PM<div class="booking" id="booking"><b>MAYA CARTER</b><br>Jordan · Botanical · Confirmed</div></div><div class="slot">4:00 PM</div></div><div class="revenue"><div><img src="/static/shop-avatar.png" alt="Studio"><b id="money">$0</b><span>recovered revenue</span></div></div></div></div></section>

<section class="stage" id="s6"><aside class="stage-nav"><div class="stage-num">06 // LEARN</div><h2>The outcome goes back into M4.</h2><p>The system remembers what worked. That is the flywheel: evidence compounds instead of disappearing.</p></aside><div class="scene"><div class="learn"><div class="learn-card"><b>Maya responded</b><span>Short-notice tolerance now has stronger evidence.</span></div><div class="learn-card"><b>Jordan converted</b><span>Artist × style × timing fit gains evidence.</span></div><div class="learn-card"><b>Offer timing worked</b><span>The intervention becomes attributable history.</span></div><div class="learn-card"><b>M4 gets stronger</b><span>The next similar opening starts with more evidence than this one did.</span></div></div></div></section>

<section class="final"><div class="ey">THE FLYWHEEL</div><h2>Every filled chair teaches the system how to fill the next one.</h2><p>That is the difference between a contact list and an intelligence layer.</p><button id="again" class="btn primary">Run It Again</button></section>
</main>
<div class="status"><span class="dot"></span><span id="status">Ready.</span><span class="grow"></span><b id="step">0 / 6</b></div>
<script>
const wait=(ms)=>new Promise(r=>setTimeout(r,ms));
const $=(s)=>document.querySelector(s), $$=(s)=>[...document.querySelectorAll(s)];
let running=false;
function reset(){running=false;$('#bar').style.width='0%';$('#status').textContent='Ready.';$('#step').textContent='0 / 6';$$('.bubble').forEach(x=>x.classList.remove('show'));$('#profile').classList.remove('show');$('#meter').classList.remove('full');$('#confidence').textContent='31%';$$('.signal').forEach(x=>x.classList.remove('on'));$$('.candidate').forEach(x=>x.classList.remove('show','win'));$('#phone').classList.remove('show');$('#claim').classList.remove('show');$('#booking').classList.remove('show');$('#money').textContent='$0';$$('.learn-card').forEach(x=>x.classList.remove('on'));}
async function stage(n,text){$('#step').textContent=`${n} / 6`;$('#status').textContent=text;$('#bar').style.width=`${n/6*100}%`;const el=$(`#s${n}`);if(el)el.scrollIntoView({behavior:'smooth',block:'center'});await wait(650)}
async function run(){if(running)return;reset();running=true;$('#status').textContent='Creating demo customer signal…';try{await fetch('/api/m4/flywheel/seed',{method:'POST'})}catch(e){}await stage(1,'Concierge is listening.');for(const b of $$('.bubble')){b.classList.add('show');await wait(380)}await stage(2,'Customer DNA is becoming usable.');$('#profile').classList.add('show');await wait(450);$('#meter').classList.add('full');$('#confidence').textContent='95%';await wait(650);await stage(3,'M4 is comparing evidence.');for(const s of $$('.signal')){s.classList.add('on');await wait(180)}for(const c of $$('.candidate')){c.classList.add('show');await wait(190)}$$('.candidate')[0].classList.add('win');await wait(700);await stage(4,'The best-fit offer is going out.');$('#phone').classList.add('show');await wait(600);$('#claim').classList.add('show');await wait(900);await stage(5,'Booking confirmed. Revenue recovered.');$('#booking').classList.add('show');await wait(650);$('#money').textContent='$550';await wait(800);await stage(6,'Outcome recorded. Intelligence updated.');for(const c of $$('.learn-card')){c.classList.add('on');await wait(260)}$('#status').textContent='Flywheel complete.';running=false;}
$('#start').addEventListener('click',run);$('#again').addEventListener('click',run);$('#replay').addEventListener('click',()=>{reset();scrollTo({top:0,behavior:'smooth'})});
reset();
</script>
</body></html>'''
