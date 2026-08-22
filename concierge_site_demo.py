"""Public sales demo showing compact Concierge chat embedded on a mock tattoo-shop site."""

import json
from fastapi.responses import HTMLResponse
import app as core


@core.app.get("/concierge-demo-widget", response_class=HTMLResponse)
def concierge_demo_widget():
    with open("templates/concierge_widget.html", "r", encoding="utf-8") as handle:
        page = handle.read()
    page = page.replace("{{ shop_id|tojson }}", json.dumps("shop_live_demo"))
    return HTMLResponse(page, headers={"Cache-Control":"no-store","Content-Security-Policy":"frame-ancestors *"})


@core.app.get("/concierge-demo", response_class=HTMLResponse)
def concierge_site_demo():
    html = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Iron Rose Tattoo · Concierge Demo</title><style>
:root{--bg:#090909;--gold:#c79a4b;--line:#29251f}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#fff;font-family:Arial,Helvetica,sans-serif}.site{min-height:100vh;background:radial-gradient(circle at 18% 25%,rgba(92,61,27,.23),transparent 32%),linear-gradient(135deg,#080808,#15110d 55%,#070707)}header{display:flex;justify-content:space-between;align-items:center;padding:22px 5vw;border-bottom:1px solid var(--line);background:rgba(5,5,5,.94)}.brand{font-family:Georgia,serif;letter-spacing:.12em;font-size:27px;line-height:.9}.brand small{font-size:13px}.nav{display:flex;gap:26px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#ddd}.hero{display:grid;grid-template-columns:1fr 430px;gap:70px;align-items:center;padding:64px 7vw 90px;min-height:760px}.copy h1{font:400 clamp(46px,6vw,76px)/1.01 Georgia,serif;margin:0 0 24px;max-width:590px}.copy p{max-width:520px;color:#b6ada3;font-size:17px;line-height:1.7}.eyebrow{color:var(--gold);letter-spacing:.18em;text-transform:uppercase;font-size:11px;margin-bottom:18px}.button{display:inline-block;margin-top:20px;padding:13px 20px;border:1px solid var(--gold);letter-spacing:.12em;text-transform:uppercase;font-size:11px}.frame-wrap{position:relative;width:100%;max-width:430px}.frame-tag{position:absolute;z-index:2;top:-12px;left:16px;background:#0b0b0b;border:1px solid #4a4032;color:#d9c199;padding:6px 10px;font:700 9px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase}.frame{width:100%;height:620px;border:0;border-radius:16px;background:transparent;box-shadow:0 30px 90px rgba(0,0,0,.55)}footer{border-top:1px solid var(--line);padding:22px 5vw;color:#766f67;font-size:11px;letter-spacing:.1em;text-transform:uppercase}@media(max-width:850px){.nav{display:none}.hero{grid-template-columns:1fr;padding:38px 5vw 60px}.frame-wrap{max-width:none}.frame{height:600px}.copy h1{font-size:52px}}
</style></head><body><div class="site"><header><div class="brand">IRON ROSE<br><small>TATTOO</small></div><div class="nav"><span>Artists</span><span>Gallery</span><span>Info</span><span>Aftercare</span><span>Contact</span></div></header><main class="hero"><section class="copy"><div class="eyebrow">Portland, Oregon · Mock Shop</div><h1>Custom tattoos made for you.</h1><p>Browse our artists, explore recent work, and tell us what you're thinking about. We'll help you figure out the right artist and next step.</p><span class="button">View artists</span></section><section class="frame-wrap"><div class="frame-tag">Live Concierge</div><iframe class="frame" src="/concierge-demo-widget" title="Tattoo Concierge" loading="eager"></iframe></section></main><footer>Iron Rose Tattoo is a fictional shop used only to demonstrate website placement.</footer></div></body></html>'''
    return HTMLResponse(html, headers={"Cache-Control":"no-store"})
