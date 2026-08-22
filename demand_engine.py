import base64
import json
import os
import re
import urllib.request
import uuid
from datetime import datetime, timezone

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.0-flash")
STYLE_TERMS = ["black and grey", "blackwork", "fine line", "traditional", "neo traditional", "realism", "illustrative", "ornamental", "geometric", "japanese", "lettering", "botanical", "color", "minimalist"]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value, default=None):
    if value is None:
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default if default is not None else {}


def _safe_name(name):
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name or "inspiration.jpg")[:120]


def _ranked(items, limit=12):
    counts = {}
    for item in items:
        key = str(item).strip().lower()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return [k for k, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))][:limit]


def _vision_analyze(image_bytes, mime_type, subject="customer inspiration"):
    if not GEMINI_API_KEY:
        return {"status": "stored_pending_analysis", "styles": [], "motifs": [], "palette": [], "line_weight": "unknown", "composition": "unknown", "confidence": 0.0, "summary": "Image stored. Vision analysis will run when GEMINI_API_KEY is configured."}
    prompt = f"""Analyze this tattoo {subject} for style matching, not copying. Return ONLY JSON with keys: styles (array), motifs (array), palette (array), line_weight, composition, density, negative_space, likely_scale, likely_placement (array), realism_level (0-1), color_level (0-1), confidence (0-1), summary. Do not identify a person, infer sensitive traits, or claim authorship. Describe visual tattoo characteristics only."""
    payload = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}}]}], "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_VISION_MODEL}:generateContent?key={GEMINI_API_KEY}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            raw = json.loads(response.read().decode())
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        result = _json(text, {})
        result["status"] = "analyzed"
        return result
    except Exception as exc:
        return {"status": "analysis_deferred", "styles": [], "motifs": [], "palette": [], "confidence": 0.0, "summary": "Image stored; analysis deferred.", "error": str(exc)[:180]}


def register_demand_engine(app, templates, connect, db_execute, db_fetchone, db_fetchall, login_required_redirect, now_iso=None):
    def ensure_schema():
        conn = connect()
        statements = [
            """CREATE TABLE IF NOT EXISTS demand_profiles (id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, customer_id TEXT NOT NULL, tattoo_dna TEXT NOT NULL DEFAULT '{}', practical_fit TEXT NOT NULL DEFAULT '{}', affinity TEXT NOT NULL DEFAULT '{}', completeness REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, UNIQUE(shop_id, customer_id))""",
            """CREATE TABLE IF NOT EXISTS demand_signals (id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, customer_id TEXT, signal_type TEXT NOT NULL, source TEXT NOT NULL, value_json TEXT NOT NULL DEFAULT '{}', confidence REAL NOT NULL DEFAULT 0, observed_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS inspiration_assets (id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, customer_id TEXT NOT NULL, filename TEXT, mime_type TEXT NOT NULL, image_b64 TEXT NOT NULL, analysis_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS concierge_inspiration_pending (id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, session_id TEXT NOT NULL, attach_token TEXT NOT NULL, filename TEXT, mime_type TEXT NOT NULL, image_b64 TEXT NOT NULL, analysis_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS artist_dna (id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, artist_id TEXT NOT NULL, dna_json TEXT NOT NULL DEFAULT '{}', confidence REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, UNIQUE(shop_id, artist_id))""",
            """CREATE TABLE IF NOT EXISTS artist_portfolio_assets (id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, artist_id TEXT NOT NULL, filename TEXT, mime_type TEXT NOT NULL, image_b64 TEXT NOT NULL, analysis_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS attribution_events (id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, customer_id TEXT, opening_id TEXT, action_type TEXT NOT NULL, channel TEXT, attribution_class TEXT NOT NULL DEFAULT 'candidate', value REAL NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)"""
        ]
        for statement in statements:
            db_execute(conn, statement)
        conn.commit(); conn.close()

    def upsert_profile(conn, shop_id, customer_id):
        row = db_fetchone(conn, "SELECT * FROM demand_profiles WHERE shop_id=? AND customer_id=?", (shop_id, customer_id))
        if row:
            return row
        pid = f"dna_{uuid.uuid4().hex[:12]}"
        db_execute(conn, "INSERT INTO demand_profiles(id,shop_id,customer_id,tattoo_dna,practical_fit,affinity,completeness,updated_at) VALUES(?,?,?,?,?,?,?,?)", (pid, shop_id, customer_id, "{}", "{}", "{}", 0, _now()))
        return db_fetchone(conn, "SELECT * FROM demand_profiles WHERE id=?", (pid,))

    def rebuild_dna(conn, shop_id, customer_id):
        profile = upsert_profile(conn, shop_id, customer_id)
        assets = db_fetchall(conn, "SELECT analysis_json FROM inspiration_assets WHERE shop_id=? AND customer_id=? ORDER BY created_at DESC", (shop_id, customer_id))
        customer = db_fetchone(conn, "SELECT * FROM customers WHERE id=? AND shop_id=?", (customer_id, shop_id))
        styles, motifs, palette, summaries, confidences = [], [], [], [], []
        for asset in assets:
            a = _json(asset["analysis_json"], {})
            styles += a.get("styles", []) or []; motifs += a.get("motifs", []) or []; palette += a.get("palette", []) or []
            if a.get("summary"): summaries.append(a["summary"])
            if isinstance(a.get("confidence"), (int, float)): confidences.append(a["confidence"])
        existing = _json(profile["tattoo_dna"], {})
        if customer:
            for key in ("preferred_styles", "tags"):
                try: source = customer[key] or ""
                except Exception: source = ""
                lower = source.lower(); styles += [term for term in STYLE_TERMS if term in lower]
        dna = dict(existing)
        dna.update({"styles": _ranked(styles), "motifs": _ranked(motifs), "palette": _ranked(palette), "visual_summary": summaries[0] if summaries else existing.get("visual_summary", ""), "inspiration_count": len(assets), "vision_confidence": round(sum(confidences)/len(confidences), 2) if confidences else 0})
        practical = _json(profile["practical_fit"], {})
        signal_count = sum(bool(dna.get(k)) for k in ["styles", "motifs", "palette", "visual_summary"]) + sum(bool(v) for v in practical.values())
        completeness = min(1.0, 0.15 + signal_count * 0.11 + min(len(assets), 3) * 0.08)
        db_execute(conn, "UPDATE demand_profiles SET tattoo_dna=?, completeness=?, updated_at=? WHERE id=?", (json.dumps(dna), completeness, _now(), profile["id"]))
        return dna, completeness

    def rebuild_artist_dna(conn, shop_id, artist_id):
        artist = db_fetchone(conn, "SELECT * FROM artists WHERE id=? AND shop_id=?", (artist_id, shop_id))
        if not artist:
            raise HTTPException(404, "Artist not found")
        assets = db_fetchall(conn, "SELECT analysis_json FROM artist_portfolio_assets WHERE shop_id=? AND artist_id=? ORDER BY created_at DESC", (shop_id, artist_id))
        styles, motifs, palette, summaries, confidences = [], [], [], [], []
        for asset in assets:
            a = _json(asset["analysis_json"], {})
            styles += a.get("styles", []) or []; motifs += a.get("motifs", []) or []; palette += a.get("palette", []) or []
            if a.get("summary"): summaries.append(a["summary"])
            if isinstance(a.get("confidence"), (int, float)): confidences.append(a["confidence"])
        manual = (artist["styles"] or "").lower()
        styles += [term for term in STYLE_TERMS if term in manual]
        dna = {"styles": _ranked(styles), "motifs": _ranked(motifs), "palette": _ranked(palette), "visual_summary": summaries[0] if summaries else "", "portfolio_count": len(assets), "source": "portfolio+artist_record"}
        confidence = round(min(0.98, (sum(confidences)/len(confidences) if confidences else 0.35) + min(len(assets), 5)*0.06), 2)
        existing = db_fetchone(conn, "SELECT id FROM artist_dna WHERE shop_id=? AND artist_id=?", (shop_id, artist_id))
        if existing:
            db_execute(conn, "UPDATE artist_dna SET dna_json=?, confidence=?, updated_at=? WHERE id=?", (json.dumps(dna), confidence, _now(), existing["id"]))
        else:
            db_execute(conn, "INSERT INTO artist_dna(id,shop_id,artist_id,dna_json,confidence,updated_at) VALUES(?,?,?,?,?,?)", (f"adna_{uuid.uuid4().hex[:12]}", shop_id, artist_id, json.dumps(dna), confidence, _now()))
        return dna, confidence

    ensure_schema()

    @app.get("/demand-graph", response_class=HTMLResponse)
    def demand_graph_page(request: Request):
        user, redirect = login_required_redirect(request)
        if redirect: return redirect
        ensure_schema(); conn = connect(); shop_id = user["shop_id"]
        shop = db_fetchone(conn, "SELECT * FROM shops WHERE id=?", (shop_id,))
        customers = db_fetchall(conn, """SELECT c.*, dp.tattoo_dna, dp.practical_fit, dp.affinity, dp.completeness, dp.updated_at AS dna_updated_at, (SELECT COUNT(*) FROM inspiration_assets ia WHERE ia.customer_id=c.id AND ia.shop_id=c.shop_id) AS inspiration_count FROM customers c LEFT JOIN demand_profiles dp ON dp.customer_id=c.id AND dp.shop_id=c.shop_id WHERE c.shop_id=? ORDER BY COALESCE(dp.completeness,0) DESC, c.name""", (shop_id,))
        artists = db_fetchall(conn, """SELECT a.*, ad.dna_json, ad.confidence AS dna_confidence FROM artists a LEFT JOIN artist_dna ad ON ad.artist_id=a.id AND ad.shop_id=a.shop_id WHERE a.shop_id=? AND a.active=1 ORDER BY a.name""", (shop_id,))
        counts = {"customers": len(customers), "artists": len(artists)}
        enriched = sum(1 for c in customers if c["tattoo_dna"]); images = sum(int(c["inspiration_count"] or 0) for c in customers)
        counts.update({"enriched": enriched, "images": images, "coverage": round((enriched / len(customers) * 100), 0) if customers else 0})
        conn.close()
        return templates.TemplateResponse(request=request, name="demand_graph.html", context={"user": user, "shop": shop, "customers": customers, "artists": artists, "counts": counts, "active_page": "demand_graph"})

    @app.post("/api/concierge/inspiration")
    async def concierge_inspiration(shop_id: str = Form(...), session_id: str = Form(...), image: UploadFile = File(...)):
        ensure_schema(); shop_id = shop_id.strip(); session_id = session_id.strip()
        if not shop_id or not session_id: raise HTTPException(400, "shop_id and session_id are required")
        if image.content_type not in ALLOWED_IMAGE_TYPES: raise HTTPException(415, "Use JPEG, PNG, or WebP.")
        data = await image.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES: raise HTTPException(413, "Image must be under 8 MB.")
        conn = connect(); shop = db_fetchone(conn, "SELECT id FROM shops WHERE id=?", (shop_id,))
        if not shop: conn.close(); raise HTTPException(404, "Shop not found")
        analysis = _vision_analyze(data, image.content_type, "inspiration")
        asset_id = f"pinsp_{uuid.uuid4().hex[:12]}"; token = uuid.uuid4().hex
        db_execute(conn, "INSERT INTO concierge_inspiration_pending(id,shop_id,session_id,attach_token,filename,mime_type,image_b64,analysis_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (asset_id, shop_id, session_id, token, _safe_name(image.filename), image.content_type, base64.b64encode(data).decode("ascii"), json.dumps(analysis), _now()))
        conn.commit(); conn.close()
        return JSONResponse({"ok": True, "asset_id": asset_id, "attach_token": token, "analysis": analysis}, headers={"Cache-Control": "no-store"})

    @app.post("/api/concierge/inspiration/attach")
    async def attach_concierge_inspiration(request: Request):
        payload = await request.json(); shop_id = str(payload.get("shop_id") or "").strip(); session_id = str(payload.get("session_id") or "").strip(); customer_id = str(payload.get("customer_id") or "").strip(); tokens = payload.get("tokens") or []
        if not all([shop_id, session_id, customer_id]) or not isinstance(tokens, list): raise HTTPException(400, "Invalid attachment request")
        ensure_schema(); conn = connect(); customer = db_fetchone(conn, "SELECT id FROM customers WHERE id=? AND shop_id=?", (customer_id, shop_id))
        if not customer: conn.close(); raise HTTPException(404, "Customer not found")
        attached = 0
        for token in tokens[:10]:
            row = db_fetchone(conn, "SELECT * FROM concierge_inspiration_pending WHERE shop_id=? AND session_id=? AND attach_token=?", (shop_id, session_id, str(token)))
            if not row: continue
            new_id = f"insp_{uuid.uuid4().hex[:12]}"
            db_execute(conn, "INSERT INTO inspiration_assets(id,shop_id,customer_id,filename,mime_type,image_b64,analysis_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (new_id, shop_id, customer_id, row["filename"], row["mime_type"], row["image_b64"], row["analysis_json"], _now()))
            a = _json(row["analysis_json"], {})
            db_execute(conn, "INSERT INTO demand_signals(id,shop_id,customer_id,signal_type,source,value_json,confidence,observed_at) VALUES(?,?,?,?,?,?,?,?)", (f"sig_{uuid.uuid4().hex[:12]}", shop_id, customer_id, "visual_inspiration", "concierge_upload", row["analysis_json"], float(a.get("confidence",0) or 0), _now()))
            db_execute(conn, "DELETE FROM concierge_inspiration_pending WHERE id=?", (row["id"],)); attached += 1
        dna, completeness = rebuild_dna(conn, shop_id, customer_id); conn.commit(); conn.close()
        return {"ok": True, "attached": attached, "tattoo_dna": dna, "completeness": completeness}

    @app.post("/api/demand-graph/customer/{customer_id}/inspiration")
    async def ingest_inspiration(request: Request, customer_id: str, image: UploadFile = File(...)):
        user, redirect = login_required_redirect(request)
        if redirect: raise HTTPException(401, "Authentication required")
        ensure_schema(); shop_id = user["shop_id"]
        if image.content_type not in ALLOWED_IMAGE_TYPES: raise HTTPException(415, "Use JPEG, PNG, or WebP.")
        data = await image.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES: raise HTTPException(413, "Image must be under 8 MB.")
        conn = connect(); customer = db_fetchone(conn, "SELECT id FROM customers WHERE id=? AND shop_id=?", (customer_id, shop_id))
        if not customer: conn.close(); raise HTTPException(404, "Customer not found")
        analysis = _vision_analyze(data, image.content_type)
        asset_id = f"insp_{uuid.uuid4().hex[:12]}"
        db_execute(conn, "INSERT INTO inspiration_assets(id,shop_id,customer_id,filename,mime_type,image_b64,analysis_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (asset_id, shop_id, customer_id, _safe_name(image.filename), image.content_type, base64.b64encode(data).decode("ascii"), json.dumps(analysis), _now()))
        db_execute(conn, "INSERT INTO demand_signals(id,shop_id,customer_id,signal_type,source,value_json,confidence,observed_at) VALUES(?,?,?,?,?,?,?,?)", (f"sig_{uuid.uuid4().hex[:12]}", shop_id, customer_id, "visual_inspiration", "customer_upload", json.dumps(analysis), float(analysis.get("confidence",0) or 0), _now()))
        dna, completeness = rebuild_dna(conn, shop_id, customer_id); conn.commit(); conn.close()
        return JSONResponse({"ok": True, "asset_id": asset_id, "analysis": analysis, "tattoo_dna": dna, "completeness": completeness})

    @app.post("/api/demand-graph/artist/{artist_id}/portfolio")
    async def ingest_artist_portfolio(request: Request, artist_id: str, image: UploadFile = File(...)):
        user, redirect = login_required_redirect(request)
        if redirect: raise HTTPException(401, "Authentication required")
        ensure_schema(); shop_id = user["shop_id"]
        if image.content_type not in ALLOWED_IMAGE_TYPES: raise HTTPException(415, "Use JPEG, PNG, or WebP.")
        data = await image.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES: raise HTTPException(413, "Image must be under 8 MB.")
        conn = connect(); artist = db_fetchone(conn, "SELECT id FROM artists WHERE id=? AND shop_id=?", (artist_id, shop_id))
        if not artist: conn.close(); raise HTTPException(404, "Artist not found")
        analysis = _vision_analyze(data, image.content_type, "artist portfolio image")
        asset_id = f"aport_{uuid.uuid4().hex[:12]}"
        db_execute(conn, "INSERT INTO artist_portfolio_assets(id,shop_id,artist_id,filename,mime_type,image_b64,analysis_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (asset_id, shop_id, artist_id, _safe_name(image.filename), image.content_type, base64.b64encode(data).decode("ascii"), json.dumps(analysis), _now()))
        dna, confidence = rebuild_artist_dna(conn, shop_id, artist_id); conn.commit(); conn.close()
        return JSONResponse({"ok": True, "asset_id": asset_id, "analysis": analysis, "artist_dna": dna, "confidence": confidence})

    @app.get("/api/demand-graph/artist/{artist_id}")
    def artist_dna_api(request: Request, artist_id: str):
        user, redirect = login_required_redirect(request)
        if redirect: raise HTTPException(401, "Authentication required")
        ensure_schema(); conn = connect(); row = db_fetchone(conn, "SELECT ad.*, (SELECT COUNT(*) FROM artist_portfolio_assets ap WHERE ap.shop_id=ad.shop_id AND ap.artist_id=ad.artist_id) AS portfolio_count FROM artist_dna ad WHERE ad.shop_id=? AND ad.artist_id=?", (user["shop_id"], artist_id)); conn.close()
        if not row: return {"artist_id": artist_id, "artist_dna": {}, "confidence": 0, "portfolio_count": 0}
        return {"artist_id": artist_id, "artist_dna": _json(row["dna_json"]), "confidence": row["confidence"], "portfolio_count": row["portfolio_count"]}

    @app.post("/api/demand-graph/customer/{customer_id}/practical")
    async def update_practical(request: Request, customer_id: str):
        user, redirect = login_required_redirect(request)
        if redirect: raise HTTPException(401, "Authentication required")
        payload = await request.json(); allowed = {"budget_min","budget_max","placement","timing","travel_radius_miles","short_notice","preferred_days","artist_preference"}; clean = {k: payload[k] for k in allowed if k in payload}
        conn = connect(); profile = upsert_profile(conn, user["shop_id"], customer_id); practical = _json(profile["practical_fit"], {}); practical.update(clean)
        db_execute(conn, "UPDATE demand_profiles SET practical_fit=?, updated_at=? WHERE id=?", (json.dumps(practical), _now(), profile["id"]))
        dna, completeness = rebuild_dna(conn, user["shop_id"], customer_id); conn.commit(); conn.close()
        return {"ok": True, "practical_fit": practical, "completeness": completeness}

    @app.get("/api/demand-graph/customer/{customer_id}")
    def customer_dna(request: Request, customer_id: str):
        user, redirect = login_required_redirect(request)
        if redirect: raise HTTPException(401, "Authentication required")
        conn = connect(); profile = db_fetchone(conn, "SELECT * FROM demand_profiles WHERE shop_id=? AND customer_id=?", (user["shop_id"], customer_id)); assets = db_fetchall(conn, "SELECT id,filename,mime_type,analysis_json,created_at FROM inspiration_assets WHERE shop_id=? AND customer_id=? ORDER BY created_at DESC", (user["shop_id"], customer_id)); conn.close()
        if not profile: return {"customer_id": customer_id, "tattoo_dna": {}, "practical_fit": {}, "affinity": {}, "completeness": 0, "assets": []}
        return {"customer_id": customer_id, "tattoo_dna": _json(profile["tattoo_dna"]), "practical_fit": _json(profile["practical_fit"]), "affinity": _json(profile["affinity"]), "completeness": profile["completeness"], "assets": [{"id":a["id"],"filename":a["filename"],"analysis":_json(a["analysis_json"]),"created_at":a["created_at"]} for a in assets]}
