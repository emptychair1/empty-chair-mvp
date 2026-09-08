"""Generated Reel screens only. No static image assets.

The launch library is intentionally limited to Empty Chair app screens and native
mobile surfaces: Setup, Login, Armed, Settings, Apple/Google Calendar, Cash App,
Square, Messages, and native Contacts import.
"""
from __future__ import annotations

import html
from fastapi.responses import HTMLResponse

import v2_app as core
import v2_instagram_reels_launch as launch
import v2_instagram_reels_engine as reels

ALLOWED = {"setup","login","armed","settings","ical","gcal","cashapp","square","sms_ios","sms_android","contacts_ios","contacts_android"}

LIBRARY = [
    {"key":"setup","family":"SETUP","title":"Set up Empty Chair","hook":"SETUP","screens":["login","setup","settings","gcal","armed"]},
    {"key":"calendar-setup","family":"SETUP","title":"Connect a calendar","hook":"CALENDAR","screens":["settings","gcal","settings","ical","armed"]},
    {"key":"payment-setup","family":"SETUP","title":"Connect payments","hook":"PAYMENTS","screens":["settings","cashapp","settings","square","armed"]},
    {"key":"add-customers-ios","family":"SETUP","title":"Add customers from iPhone","hook":"CUSTOMERS","screens":["settings","contacts_ios","contacts_ios","settings","armed"]},
    {"key":"add-customers-android","family":"SETUP","title":"Add customers from Android","hook":"CUSTOMERS","screens":["settings","contacts_android","contacts_android","settings","armed"]},
    {"key":"armed-ios","family":"PRODUCT","title":"Armed on iPhone","hook":"ARMED","screens":["login","settings","ical","sms_ios","armed"]},
    {"key":"armed-android","family":"PRODUCT","title":"Armed on Android","hook":"ARMED","screens":["login","settings","gcal","sms_android","armed"]},
    {"key":"cashapp-flow","family":"PRODUCT","title":"Cash App deposit flow","hook":"CASH APP","screens":["armed","sms_ios","cashapp","ical","armed"]},
    {"key":"square-flow","family":"PRODUCT","title":"Square deposit flow","hook":"SQUARE","screens":["armed","sms_android","square","gcal","armed"]},
    {"key":"settings","family":"PRODUCT","title":"Empty Chair settings","hook":"SETTINGS","screens":["login","settings","gcal","square","armed"]},
]
launch.PRODUCT_LIBRARY = LIBRARY
launch.PRODUCT_SCENES = 5


def shell(body: str, css: str, label: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><style>*{{box-sizing:border-box}}html,body{{margin:0;width:1080px;height:1920px;overflow:hidden}}body{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}{css}</style></head><body><main aria-label='{html.escape(label)}'>{body}</main></body></html>"


def ec(screen: str) -> str:
    titles={"login":"WELCOME BACK.","setup":"SET UP YOUR STUDIO.","armed":"ARMED.","settings":"SETTINGS"}
    body=f"<header><b>EMPTY CHAIR</b><span>2.0</span></header><section><h1>{titles[screen]}</h1>"
    if screen=="login": body += "<label>EMAIL</label><div class='field'>artist@studio.com</div><label>PASSWORD</label><div class='field'>••••••••••••</div><div class='btn'>LOG IN</div>"
    elif screen=="setup": body += "<label>STUDIO</label><div class='field'>Blackbird Tattoo</div><label>ARTIST</label><div class='field'>Mara</div><div class='btn'>CONTINUE</div>"
    elif screen=="settings": body += "<div class='row'>CALENDAR <b>CONNECTED ✓</b></div><div class='row'>PAYMENTS <b>CONNECTED ✓</b></div><div class='row'>CUSTOMERS <b>ADD FROM CONTACTS ›</b></div><div class='row'>RECOVERY <b>ON ✓</b></div>"
    else: body += "<div class='armed'>●</div><p>WATCHING YOUR CALENDAR</p><div class='row'>CALENDAR <b>CONNECTED ✓</b></div><div class='row'>PAYMENTS <b>READY ✓</b></div><div class='row'>CUSTOMERS <b>READY ✓</b></div>"
    body += "</section>"
    css="main{width:1080px;height:1920px;background:#0B0905;color:#FFB000;padding:72px 58px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}header{display:flex;justify-content:space-between;border-bottom:1px solid #332300;padding-bottom:24px;font-size:24px}section{padding-top:210px}h1{font-size:62px;color:#FFD36A;font-weight:500;margin-bottom:90px}label{display:block;color:#805800;font-size:22px;margin:35px 0 12px}.field,.row{border:1px solid #5f4100;padding:28px;font-size:28px;margin:18px 0}.row{display:flex;justify-content:space-between}.row b{color:#FFD36A}.btn{border:2px solid #FFB000;text-align:center;padding:30px;margin-top:70px;font-size:30px;color:#FFD36A}.armed{font-size:120px;color:#FFD36A}p{font-size:30px;color:#FFD36A;margin-bottom:80px}"
    return shell(body,css,f"Empty Chair {screen}")


def ios_calendar() -> str:
    return reels._calendar_screen({"day":"TUE","time":"3:00 PM","duration":"3 hr","old_client":"Avery","client":"Jess","value":450},recovered=True)


def google_calendar() -> str:
    body="<div class='bar'><b>September</b><span>⌕　☰</span></div><div class='days'>MON　 TUE　 WED　 THU　 FRI</div><div class='grid'><div class='time'>12 PM</div><div class='event'><b>Jess — Tattoo</b><br>3:00 PM · 3 hr</div></div><div class='fab'>＋</div>"
    css="main{width:1080px;height:1920px;background:#fff;color:#202124;padding:70px 42px}.bar{display:flex;justify-content:space-between;font-size:34px;padding:20px 0 45px}.days{border-bottom:1px solid #dadce0;padding:30px 0;font-size:23px}.grid{height:1400px;position:relative;background:repeating-linear-gradient(#fff 0,#fff 159px,#e8eaed 160px)}.time{padding-top:470px;color:#5f6368}.event{position:absolute;top:520px;left:160px;right:40px;background:#d2e3fc;border-left:8px solid #1a73e8;border-radius:10px;padding:25px;font-size:27px}.fab{position:absolute;right:55px;bottom:70px;width:90px;height:90px;border-radius:28px;box-shadow:0 2px 12px #bbb;display:grid;place-items:center;font-size:48px;color:#1a73e8;background:#fff}"
    return shell(body,css,"Google Calendar")


def contacts(platform: str) -> str:
    ios=platform=="ios"
    body="<div class='top'><span>Cancel</span><b>Select Contacts</b><span>Done</span></div><div class='search'>Search</div>" + ''.join(f"<div class='contact'><span class='check'>{'✓' if i<3 else ''}</span><div><b>{n}</b><small>{p}</small></div></div>" for i,(n,p) in enumerate([('Jess Carter','(555) 013-2184'),('Sam Rivera','(555) 016-9002'),('Taylor Reed','(555) 012-7714'),('Jordan Lee','(555) 014-4420'),('Casey Morgan','(555) 019-1138')]))
    css=f"main{{width:1080px;height:1920px;background:{'#f2f2f7' if ios else '#fff'};color:#111;padding:70px 35px}}.top{{display:flex;justify-content:space-between;align-items:center;font-size:27px;padding:25px 8px 35px}}.top span{{color:{'#007aff' if ios else '#1a73e8'}}}.search{{background:{'#e5e5ea' if ios else '#f1f3f4'};border-radius:18px;padding:20px 28px;color:#777;font-size:25px;margin-bottom:25px}}.contact{{height:145px;background:#fff;border-bottom:1px solid #ddd;display:flex;align-items:center;gap:28px;padding:15px}}.check{{width:48px;height:48px;border:2px solid {'#007aff' if ios else '#1a73e8'};border-radius:50%;display:grid;place-items:center;color:{'#007aff' if ios else '#1a73e8'};font-size:28px}}.contact b{{font-size:28px}}.contact small{{display:block;color:#777;font-size:22px;margin-top:8px}}"
    return shell(body,css,f"{'iOS' if ios else 'Android'} Contacts")


def cashapp() -> str:
    body="<div class='top'><b>Cash App</b><span>◉</span></div><div class='money'>$80.00</div><div class='status'>Payment completed</div><div class='card'><b>Empty Chair deposit</b><span>Jess · Tattoo appointment</span><strong>+$80.00</strong></div>"
    css="main{width:1080px;height:1920px;background:#fff;color:#111;padding:75px 50px}.top{display:flex;justify-content:space-between;font-size:32px}.top b,.status{color:#00a86b}.money{text-align:center;font-size:110px;font-weight:700;margin-top:300px}.status{text-align:center;font-size:27px;margin-top:25px}.card{margin-top:180px;border-top:1px solid #ddd;border-bottom:1px solid #ddd;padding:35px 10px;display:grid;grid-template-columns:1fr auto;gap:12px;font-size:27px}.card span{color:#777}.card strong{grid-column:2;grid-row:1/3;color:#00a86b}"
    return shell(body,css,"Cash App payment")


def sms(android: bool) -> str:
    msg="EMPTY CHAIR // OPEN\n\nMara has an opening.\nTUE // 3:00 PM\n3 hr\n$450\n\nTAKE THE CHAIR\napp.tryemptychair.com/o/••••••••"
    if not android: return reels._sms_screen("CLIENT PHONE",msg,"Messages")
    body=f"<div class='top'>‹　<b>Empty Chair</b>　⋮</div><div class='bubble'><pre>{html.escape(msg)}</pre></div><div class='compose'>Message　　＋</div>"
    css="main{width:1080px;height:1920px;background:#fff;color:#202124;padding:70px 35px}.top{text-align:center;border-bottom:1px solid #ddd;padding:25px;font-size:29px}.bubble{margin-top:170px;background:#d3e3fd;border-radius:30px 30px 8px 30px;padding:30px;max-width:88%;margin-left:auto}.bubble pre{white-space:pre-wrap;font:29px/1.4 Roboto,Arial,sans-serif}.compose{position:absolute;bottom:70px;left:40px;right:40px;border:1px solid #ddd;border-radius:35px;padding:22px;color:#777;font-size:25px}"
    return shell(body,css,"Android Messages")


def render(kind: str) -> str:
    if kind not in ALLOWED: raise RuntimeError(f"Blocked Reel screen type: {kind}")
    if kind in {"setup","login","armed","settings"}: return ec(kind)
    if kind=="ical": return ios_calendar()
    if kind=="gcal": return google_calendar()
    if kind=="cashapp": return cashapp()
    if kind=="square": return reels._square_screen({"deposit":80,"client":"Jess","time":"3:00 PM"})
    if kind=="sms_ios": return sms(False)
    if kind=="sms_android": return sms(True)
    if kind=="contacts_ios": return contacts("ios")
    return contacts("android")


def product_html(item: dict, scene: int) -> str:
    screens=item.get("screens") or []
    if scene < 0 or scene >= len(screens): raise RuntimeError("Invalid Reel scene")
    return render(str(screens[scene]))

launch._product_html = product_html

print("Instagram Reels generated-screen library loaded // zero static image assets", flush=True)
