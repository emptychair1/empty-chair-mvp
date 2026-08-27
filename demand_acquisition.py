"""Demand Acquisition: zero-data artist demand generation and tracked acquisition."""
import html
import re
import uuid
from urllib.parse import urlencode

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core

POLICY_VERSION = "marketplace-guard-2026-08-27"
STARTER_CAMPAIGNS = [
    ("Traditional Animals", "Traditional animal tattoo concepts — snakes, birds, panthers and creatures"),
    ("Weird / Psychedelic", "Weird and psychedelic tattoo concepts — mushrooms, frogs and surreal imagery"),
    ("Moths / Bugs / Nature", "Nature-inspired tattoo concepts — moths, insects, flowers and botanical imagery"),
    ("Dark Traditional", "Dark traditional tattoo concepts — skulls, daggers and occult-inspired imagery"),
    ("Custom Traditional", "Custom traditional and neo-traditional tattoo concepts built around your idea"),
]


def _e(value):
    return html.escape(str(value or ""), quote=True)


def _ensure_column(conn, table, column, ddl):
    if getattr(core, "USE_POSTGRES", False):
        core.db_execute(conn, f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")
        return
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        core.db_execute(conn, f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _ensure_tables(conn):
    core.db_execute(conn, """CREATE TABLE IF NOT EXISTS acquisition_identities (
        id TEXT PRIMARY KEY, owner_shop_id TEXT NOT NULL, artist_name TEXT NOT NULL,
        studio_name TEXT NOT NULL DEFAULT '', studio_address TEXT NOT NULL DEFAULT '',
        minimum_price INTEGER NOT NULL DEFAULT 0, pricing_model TEXT NOT NULL DEFAULT '',
        styles TEXT NOT NULL DEFAULT '', subjects TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    core.db_execute(conn, """CREATE TABLE IF NOT EXISTS acquisition_campaigns (
        id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, artist_id TEXT, identity_id TEXT,
        name TEXT NOT NULL, channel TEXT NOT NULL, hook TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    core.db_execute(conn, """CREATE TABLE IF NOT EXISTS acquisition_visits (
        id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, shop_id TEXT NOT NULL,
        source TEXT NOT NULL, created_at TEXT NOT NULL)""")
    _ensure_column(conn, "acquisition_campaigns", "identity_id", "TEXT")
    _ensure_column(conn, "acquisition_campaigns", "listing_title", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "acquisition_campaigns", "listing_copy", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "acquisition_campaigns", "compliance_status", "TEXT NOT NULL DEFAULT 'unchecked'")
    _ensure_column(conn, "acquisition_campaigns", "compliance_score", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "acquisition_campaigns", "compliance_notes", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "acquisition_campaigns", "policy_version", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "acquisition_campaigns", "policy_checked_at", "TEXT")
    conn.commit()


def marketplace_guard(title, copy):
    """Conservative preflight. It does not guarantee Meta approval or attempt moderation evasion."""
    text = f"{title} {copy}".lower()
    notes = []
    score = 100
    red = [
        (r"\bguaranteed\b|\bguarantee\b", "Avoid guarantees or outcome claims."),
        (r"\bfree tattoo\b", "Avoid potentially misleading free-service claims."),
        (r"\bno id\b|\bunder 18\b|\bminor\b", "Age/ID language requires manual review."),
        (r"\bvenmo\b|\bcashapp\b|\bzelle\b", "Keep payment instructions out of acquisition copy."),
    ]
    yellow = [
        (r"https?://|www\.", "External links in listing copy can create channel risk; use the tracked link only where permitted."),
        (r"\bdeposit\b|\bpay now\b", "Move transaction language to Concierge rather than the discovery listing."),
        (r"!!!+|\$\$\$+", "Reduce spam-like punctuation."),
    ]
    for pattern, note in red:
        if re.search(pattern, text):
            score -= 45
            notes.append(note)
    for pattern, note in yellow:
        if re.search(pattern, text):
            score -= 15
            notes.append(note)
    if len(copy.strip()) < 45:
        score -= 10
        notes.append("Copy is very short; add clear, truthful context.")
    score = max(0, min(100, score))
    status = "red" if score < 60 else "yellow" if score < 85 else "green"
    if not notes:
        notes.append("No local copy-risk rules triggered. Confirm the channel currently permits this listing type before posting.")
    return status, score, " ".join(notes)


def record_lead_attribution(conn, lead_id, campaign_id, source):
    if not campaign_id and not source:
        return
    _ensure_tables(conn)
    _ensure_column(conn, "concierge_leads", "campaign_id", "TEXT")
    _ensure_column(conn, "concierge_leads", "acquisition_source", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "concierge_leads", "acquisition_identity_id", "TEXT")
    identity_id = None
    if campaign_id:
        campaign = core.db_fetchone(conn, "SELECT identity_id FROM acquisition_campaigns WHERE id=?", (campaign_id,))
        if campaign:
            identity_id = campaign["identity_id"]
    core.db_execute(conn, "UPDATE concierge_leads SET campaign_id=?, acquisition_source=?, acquisition_identity_id=? WHERE id=?",
                    (campaign_id or None, source or "", identity_id, lead_id))
    conn.commit()


def _campaign_url(request, campaign):
    base = str(request.base_url).rstrip("/")
    return f"{base}/a/{campaign['id']}?" + urlencode({"shop_id": campaign["shop_id"], "campaign_id": campaign["id"], "src": campaign["channel"]})


@core.app.get("/a/{campaign_id}")
def acquisition_entry(campaign_id: str):
    conn = core.connect()
    try:
        _ensure_tables(conn)
        campaign = core.db_fetchone(conn, "SELECT * FROM acquisition_campaigns WHERE id=? AND status='active'", (campaign_id,))
        if not campaign:
            return RedirectResponse("/concierge", status_code=302)
        core.db_execute(conn, "INSERT INTO acquisition_visits(id,campaign_id,shop_id,source,created_at) VALUES (?,?,?,?,?)",
                        (f"visit_{uuid.uuid4().hex[:12]}", campaign_id, campaign["shop_id"], campaign["channel"], core.now_iso()))
        conn.commit()
        return RedirectResponse("/concierge?" + urlencode({"shop_id": campaign["shop_id"], "campaign_id": campaign_id, "src": campaign["channel"]}), status_code=302)
    finally:
        conn.close()


@core.app.get("/demand-acquisition", response_class=HTMLResponse)
def demand_acquisition_dashboard(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        identities = core.db_fetchall(conn, "SELECT * FROM acquisition_identities WHERE owner_shop_id=? AND status='active' ORDER BY created_at DESC", (user["shop_id"],))
        campaigns = core.db_fetchall(conn, """SELECT c.*, i.artist_name, i.studio_name,
            (SELECT COUNT(*) FROM acquisition_visits v WHERE v.campaign_id=c.id) AS visits,
            (SELECT COUNT(*) FROM concierge_leads l WHERE l.shop_id=c.shop_id AND l.campaign_id=c.id) AS leads
            FROM acquisition_campaigns c LEFT JOIN acquisition_identities i ON i.id=c.identity_id
            WHERE c.shop_id=? ORDER BY c.created_at DESC""", (user["shop_id"],))
    except Exception:
        conn.rollback(); identities, campaigns = [], []
    finally:
        conn.close()

    identity_cards = "".join(f"<article><b>{_e(i['artist_name'])}</b><span>ARTIST IDENTITY</span><p>{_e(i['studio_name'])}<br>{_e(i['studio_address'])}</p><small>${int(i['minimum_price'] or 0)} minimum · {_e(i['pricing_model'])}<br>{_e(i['styles'])}<br>{_e(i['subjects'])}</small></article>" for i in identities) or "<p class='empty'>No artist acquisition identity yet.</p>"
    options = "".join(f"<option value='{_e(i['id'])}'>{_e(i['artist_name'])} @ {_e(i['studio_name'] or 'independent')}</option>" for i in identities)
    cards = []
    for c in campaigns:
        url = _campaign_url(request, c)
        status = c["compliance_status"] or "unchecked"
        cards.append(f"""<article class='campaign'><div><b>{_e(c['name'])}</b><span class='{_e(status)}'>{_e(status)} · {int(c['compliance_score'] or 0)}/100</span></div><div class='owner'>{_e(c['artist_name'])} @ {_e(c['studio_name'])} · {_e(c['channel'])}</div><h3>{_e(c['listing_title'] or c['name'])}</h3><p>{_e(c['listing_copy'] or c['hook'])}</p><small>{_e(c['compliance_notes'])}<br>Policy: {_e(c['policy_version'] or 'not checked')}</small><div class='metrics'>{int(c['visits'] or 0)} visits · {int(c['leads'] or 0)} leads</div><label>TRACKED CONCIERGE LINK</label><input value='{_e(url)}' readonly onclick='this.select()'></article>""")
    campaign_body = "".join(cards) or "<p class='empty'>No campaigns yet.</p>"
    launch = f"<form method='post' action='/demand-acquisition/starter-campaigns'><h2>Launch first experiment</h2><p>Create the five portfolio-derived demand hypotheses with compliance preflight and tracked Concierge links.</p><label>ARTIST IDENTITY</label><select name='identity_id' required>{options}</select><button>Create 5 starter campaigns</button></form>" if identities else ""
    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Demand Acquisition · Empty Chair</title><style>body{{margin:0;background:#080a08;color:#f0eadf;font-family:Inter,system-ui,sans-serif}}main{{max-width:1050px;margin:auto;padding:30px}}h1{{font-size:42px;margin:5px 0}}h2{{margin-top:0}}.ey{{color:#d8ff45;font:700 11px monospace;letter-spacing:.15em}}form,article{{border:1px solid #30362e;background:#0e110e;padding:18px;margin:14px 0}}label{{display:block;font-size:11px;color:#9ba197;margin-top:12px}}input,select{{box-sizing:border-box;width:100%;padding:11px;margin-top:5px;background:#090b09;color:#f0eadf;border:1px solid #353c33}}button{{margin-top:15px;padding:12px 18px;background:#d8ff45;border:0;font-weight:900}}article span{{float:right;font:700 11px monospace;text-transform:uppercase}}small,.owner{{color:#9ba197}}.owner{{margin-top:6px;font-size:12px}}a{{color:#d8ff45}}.green{{color:#d8ff45}}.yellow{{color:#ffd45b}}.red{{color:#ff6961}}.metrics{{margin-top:12px;font-weight:800}}</style></head><body><main><a href='/'>← App</a><div class='ey'>M4 · ZERO-DATA DEMAND ENGINE</div><h1>Demand Launch Console</h1><p>Generate free-channel campaigns, preflight copy, track acquisition, and learn which demand hypothesis converts.</p><form method='post' action='/demand-acquisition/identities'><h2>Artist acquisition identity</h2><label>ARTIST NAME</label><input name='artist_name' required value='Josh Daniels'><label>WORKING STUDIO</label><input name='studio_name' required value='Blind Wolf Tattoo'><label>STUDIO ADDRESS</label><input name='studio_address' required value='50 Gaines School Rd Ste 13, Athens, GA 30605'><label>MINIMUM PRICE</label><input name='minimum_price' type='number' min='0' value='100'><label>PRICING MODEL</label><input name='pricing_model' value='Hand-size / palm-size pricing'><label>PRIMARY STYLES</label><input name='styles' value='American Traditional, Neo-Traditional'><label>SUBJECTS</label><input name='subjects' value='Animals, birds, insects and moths, botanical and nature, psychedelic and whimsical imagery, dark and occult-inspired traditional, unusual remixes of classic traditional motifs'><button>Create artist identity</button></form>{identity_cards}{launch}<section>{campaign_body}</section></main></body></html>"", headers={"Cache-Control":"no-store"})


@core.app.post("/demand-acquisition/identities")
def create_acquisition_identity(request: Request, artist_name: str = Form(...), studio_name: str = Form(""), studio_address: str = Form(""), minimum_price: int = Form(0), pricing_model: str = Form(""), styles: str = Form(""), subjects: str = Form("")):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    identity_id, now = f"acq_identity_{uuid.uuid4().hex[:12]}", core.now_iso()
    conn = core.connect()
    try:
        _ensure_tables(conn)
        core.db_execute(conn, "INSERT INTO acquisition_identities(id,owner_shop_id,artist_name,studio_name,studio_address,minimum_price,pricing_model,styles,subjects,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (identity_id,user["shop_id"],artist_name.strip(),studio_name.strip(),studio_address.strip(),max(0,int(minimum_price or 0)),pricing_model.strip(),styles.strip(),subjects.strip(),"active",now,now))
        conn.commit()
    finally: conn.close()
    return RedirectResponse("/demand-acquisition", status_code=303)


@core.app.post("/demand-acquisition/starter-campaigns")
def create_starter_campaigns(request: Request, identity_id: str = Form(...)):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        identity = core.db_fetchone(conn, "SELECT * FROM acquisition_identities WHERE id=? AND owner_shop_id=? AND status='active'", (identity_id.strip(), user["shop_id"]))
        if not identity: return HTMLResponse("Invalid artist acquisition identity.", status_code=400)
        now = core.now_iso()
        for name, hook in STARTER_CAMPAIGNS:
            existing = core.db_fetchone(conn, "SELECT id FROM acquisition_campaigns WHERE shop_id=? AND identity_id=? AND name=? AND channel='facebook_marketplace'", (user["shop_id"], identity_id, name))
            if existing: continue
            title = f"{name} Tattoo Concepts — Athens"
            copy = f"Original {hook.lower()} by {identity['artist_name']}, working at {identity['studio_name']} in Athens. $100 minimum; pricing is based on approximate hand/palm size. Message through the linked Tattoo Concierge with your idea, placement, size, budget and timing to see whether it is a fit."
            status, score, notes = marketplace_guard(title, copy)
            core.db_execute(conn, """INSERT INTO acquisition_campaigns(id,shop_id,artist_id,identity_id,name,channel,hook,status,created_at,updated_at,listing_title,listing_copy,compliance_status,compliance_score,compliance_notes,policy_version,policy_checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (f"camp_{uuid.uuid4().hex[:12]}",user["shop_id"],None,identity_id,name,"facebook_marketplace",hook,"active",now,now,title,copy,status,score,notes,POLICY_VERSION,now))
        conn.commit()
    finally: conn.close()
    return RedirectResponse("/demand-acquisition", status_code=303)
