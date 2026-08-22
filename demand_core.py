"""Shared private Demand Graph primitives."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import app as core


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_value(value, default=None):
    if value is None:
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {} if default is None else default


def ensure_schema(conn=None):
    owns = conn is None
    conn = conn or core.connect()
    try:
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS demand_profiles (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            tattoo_dna TEXT NOT NULL DEFAULT '{}',
            practical_fit TEXT NOT NULL DEFAULT '{}',
            affinity TEXT NOT NULL DEFAULT '{}',
            completeness REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            UNIQUE(shop_id, customer_id)
        )""")
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS demand_signals (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            customer_id TEXT,
            signal_type TEXT NOT NULL,
            source TEXT NOT NULL,
            value_json TEXT NOT NULL DEFAULT '{}',
            confidence REAL NOT NULL DEFAULT 0,
            observed_at TEXT NOT NULL
        )""")
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS attribution_events (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            customer_id TEXT,
            opening_id TEXT,
            action_type TEXT NOT NULL,
            channel TEXT,
            attribution_class TEXT NOT NULL DEFAULT 'candidate',
            value REAL NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )""")
        core.db_execute(conn, "CREATE INDEX IF NOT EXISTS idx_demand_signals_customer ON demand_signals(shop_id,customer_id,observed_at)")
        core.db_execute(conn, "CREATE INDEX IF NOT EXISTS idx_attribution_customer ON attribution_events(shop_id,customer_id,created_at)")
        core.db_execute(conn, "CREATE INDEX IF NOT EXISTS idx_attribution_opening ON attribution_events(shop_id,opening_id,created_at)")
        if owns:
            conn.commit()
    finally:
        if owns:
            conn.close()


def record_signal(shop_id, customer_id, signal_type, source, value, confidence=1.0, observed_at=None, conn=None):
    if not shop_id or not customer_id or not signal_type or not source:
        return None
    owns = conn is None
    conn = conn or core.connect()
    try:
        ensure_schema(conn)
        signal_id = f"sig_{uuid.uuid4().hex[:12]}"
        core.db_execute(
            conn,
            "INSERT INTO demand_signals(id,shop_id,customer_id,signal_type,source,value_json,confidence,observed_at) VALUES(?,?,?,?,?,?,?,?)",
            (signal_id, str(shop_id), str(customer_id), str(signal_type), str(source), json.dumps(value), max(0.0, min(1.0, float(confidence or 0))), observed_at or now_iso()),
        )
        if owns:
            conn.commit()
        return signal_id
    finally:
        if owns:
            conn.close()


def capture_concierge_profile(shop_id, customer_id, profile, conn=None):
    """Persist zero-party Concierge answers as provenance-bearing evidence."""
    if not isinstance(profile, dict):
        return []
    mapping = {
        "project": "declared.project",
        "styles": "declared.styles",
        "placement": "declared.placement",
        "budget": "declared.budget",
        "timing": "declared.timing",
        "short_notice": "declared.short_notice",
        "artist_vibe": "declared.artist_preference",
        "travel": "declared.travel",
        "contact_preference": "declared.contact_preference",
        "offer_opt_in": "consent.opening_outreach",
    }
    owns = conn is None
    conn = conn or core.connect()
    ids = []
    try:
        ensure_schema(conn)
        for key, signal_type in mapping.items():
            value = profile.get(key)
            if value in (None, ""):
                continue
            sid = record_signal(shop_id, customer_id, signal_type, "concierge_zero_party", {"value": value}, 1.0, conn=conn)
            if sid:
                ids.append(sid)
        if owns:
            conn.commit()
        return ids
    finally:
        if owns:
            conn.close()


def sync_concierge_profile(shop_id, customer_id, profile, conn=None):
    """Make Concierge zero-party answers immediately available to M4."""
    if not isinstance(profile, dict):
        return None
    owns = conn is None
    conn = conn or core.connect()
    try:
        ensure_schema(conn)
        row = core.db_fetchone(conn, "SELECT * FROM demand_profiles WHERE shop_id=? AND customer_id=?", (shop_id, customer_id))
        if row:
            tattoo = json_value(row["tattoo_dna"], {})
            practical = json_value(row["practical_fit"], {})
            affinity = json_value(row["affinity"], {})
            profile_id = row["id"]
        else:
            tattoo, practical, affinity = {}, {}, {}
            profile_id = f"dna_{uuid.uuid4().hex[:12]}"
            core.db_execute(conn, "INSERT INTO demand_profiles(id,shop_id,customer_id,tattoo_dna,practical_fit,affinity,completeness,updated_at) VALUES(?,?,?,?,?,?,?,?)", (profile_id, shop_id, customer_id, "{}", "{}", "{}", 0.0, now_iso()))

        styles = str(profile.get("styles") or "").strip()
        if styles:
            existing = tattoo.get("styles") or []
            if not isinstance(existing, list):
                existing = [str(existing)]
            incoming = [x.strip().lower() for x in styles.replace(";", ",").split(",") if x.strip()]
            tattoo["styles"] = list(dict.fromkeys([str(x).strip().lower() for x in existing if str(x).strip()] + incoming))[:12]
        if profile.get("project"):
            tattoo["declared_project"] = profile.get("project")

        practical_map = {
            "placement": "placement",
            "budget": "budget",
            "timing": "timing",
            "short_notice": "short_notice",
            "travel": "travel",
            "artist_vibe": "artist_preference",
        }
        for source_key, target_key in practical_map.items():
            value = profile.get(source_key)
            if value not in (None, ""):
                practical[target_key] = value
        if profile.get("artist_vibe"):
            affinity["declared_artist_preference"] = profile.get("artist_vibe")

        populated = sum(bool(v) for v in practical.values()) + sum(bool(tattoo.get(k)) for k in ("styles", "motifs", "palette", "visual_summary", "declared_project"))
        completeness = min(1.0, max(float(row["completeness"] or 0) if row else 0.0, 0.15 + populated * 0.08))
        core.db_execute(conn, "UPDATE demand_profiles SET tattoo_dna=?, practical_fit=?, affinity=?, completeness=?, updated_at=? WHERE id=?", (json.dumps(tattoo), json.dumps(practical), json.dumps(affinity), completeness, now_iso(), profile_id))
        if owns:
            conn.commit()
        return {"tattoo_dna": tattoo, "practical_fit": practical, "affinity": affinity, "completeness": completeness}
    finally:
        if owns:
            conn.close()


def record_attribution(shop_id, customer_id, opening_id, action_type, channel=None, attribution_class="candidate", value=0.0, metadata=None, conn=None):
    if not shop_id or not action_type:
        return None
    owns = conn is None
    conn = conn or core.connect()
    try:
        ensure_schema(conn)
        event_id = f"attr_{uuid.uuid4().hex[:12]}"
        core.db_execute(
            conn,
            "INSERT INTO attribution_events(id,shop_id,customer_id,opening_id,action_type,channel,attribution_class,value,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (event_id, str(shop_id), str(customer_id) if customer_id else None, str(opening_id) if opening_id else None, str(action_type), str(channel) if channel else None, str(attribution_class or "candidate"), float(value or 0), json.dumps(metadata or {}), now_iso()),
        )
        if owns:
            conn.commit()
        return event_id
    finally:
        if owns:
            conn.close()


def customer_intelligence(shop_id, customer_id):
    """Return one coherent shop-private customer intelligence object."""
    conn = core.connect()
    try:
        ensure_schema(conn)
        customer = core.db_fetchone(conn, "SELECT * FROM customers WHERE id=? AND shop_id=?", (customer_id, shop_id))
        if not customer:
            return None
        try:
            profile = core.db_fetchone(conn, "SELECT * FROM demand_profiles WHERE shop_id=? AND customer_id=?", (shop_id, customer_id))
        except Exception:
            profile = None
        try:
            lead = core.db_fetchone(conn, "SELECT profile_json,m4_confidence,created_at FROM concierge_leads WHERE shop_id=? AND customer_id=? ORDER BY created_at DESC LIMIT 1", (shop_id, customer_id))
        except Exception:
            lead = None
        signals = core.db_fetchall(conn, "SELECT signal_type,source,value_json,confidence,observed_at FROM demand_signals WHERE shop_id=? AND customer_id=? ORDER BY observed_at DESC", (shop_id, customer_id))
        bookings = core.db_fetchall(conn, "SELECT b.status,b.amount,b.booked_at,b.artist_id,b.opening_id FROM bookings b JOIN openings o ON o.id=b.opening_id WHERE b.customer_id=? AND o.shop_id=? ORDER BY COALESCE(b.booked_at,'') DESC", (customer_id, shop_id))
        attrs = core.db_fetchall(conn, "SELECT action_type,channel,attribution_class,value,metadata_json,created_at,opening_id FROM attribution_events WHERE shop_id=? AND customer_id=? ORDER BY created_at DESC LIMIT 100", (shop_id, customer_id))

        declared = json_value(lead["profile_json"], {}) if lead else {}
        tattoo = json_value(profile["tattoo_dna"], {}) if profile else {}
        practical = json_value(profile["practical_fit"], {}) if profile else {}
        affinity = json_value(profile["affinity"], {}) if profile else {}
        behavior = {
            "appointment_count": int(customer["appointment_count"] or 0) if "appointment_count" in customer.keys() else len(bookings),
            "completed_count": int(customer["completed_count"] or 0) if "completed_count" in customer.keys() else 0,
            "cancelled_count": int(customer["cancellation_count"] or 0) if "cancellation_count" in customer.keys() else 0,
            "lifetime_value": (float(customer["average_spend"] or 0) * int(customer["completed_count"] or 0)) if "average_spend" in customer.keys() and "completed_count" in customer.keys() else sum(float(b["amount"] or 0) for b in bookings if b["status"] in ("CONFIRMED", "COMPLETED")),
            "last_offer_at": customer["last_offer_at"] if "last_offer_at" in customer.keys() else None,
            "recent_bookings": [dict(b) for b in bookings[:20]],
        }
        provenance = [{"signal_type": s["signal_type"], "source": s["source"], "value": json_value(s["value_json"], {}), "confidence": float(s["confidence"] or 0), "observed_at": s["observed_at"]} for s in signals]
        return {
            "shop_id": str(shop_id),
            "customer_id": str(customer_id),
            "identity": {"name": customer["name"], "phone": customer["phone"], "email": customer["email"], "communication_consent": bool(customer["communication_consent"])},
            "declared": declared,
            "behavioral": behavior,
            "visual": tattoo,
            "practical": practical,
            "affinity": affinity,
            "contextual": {},
            "provenance": provenance,
            "attribution": [{**dict(a), "metadata": json_value(a["metadata_json"], {})} for a in attrs],
            "completeness": float(profile["completeness"] or 0) if profile else 0.0,
            "concierge_confidence": int(lead["m4_confidence"] or 0) if lead else 0,
        }
    finally:
        conn.close()
