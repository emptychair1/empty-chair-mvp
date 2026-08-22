"""Enrichment V1 for the private Empty Chair Demand Graph.

This module deliberately treats external geography as contextual evidence, not as
individual customer truth. Customer/shop locations must be explicitly supplied.
All derived facts are persisted with source, confidence, and observed_at.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import app as core
import demand_core

CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
CENSUS_ACS_URL = "https://api.census.gov/data/2024/acs/acs5"
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving"
USER_AGENT = "EmptyChair/1.0 (+https://tryemptychair.com)"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_get(url: str, timeout: int = 8):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_schema(conn=None):
    owns = conn is None
    conn = conn or core.connect()
    try:
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS enrichment_locations (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            address_text TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            state_fips TEXT,
            county_fips TEXT,
            tract TEXT,
            source TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            observed_at TEXT NOT NULL,
            UNIQUE(shop_id, entity_type, entity_id)
        )""")
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS enrichment_context (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            context_json TEXT NOT NULL DEFAULT '{}',
            source TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            observed_at TEXT NOT NULL,
            UNIQUE(shop_id, customer_id)
        )""")
        core.db_execute(conn, "CREATE INDEX IF NOT EXISTS idx_enrichment_location ON enrichment_locations(shop_id,entity_type,entity_id)")
        core.db_execute(conn, "CREATE INDEX IF NOT EXISTS idx_enrichment_customer ON enrichment_context(shop_id,customer_id)")
        if owns:
            conn.commit()
    finally:
        if owns:
            conn.close()


def _upsert_location(conn, shop_id, entity_type, entity_id, address, geo, source):
    import uuid
    existing = core.db_fetchone(conn, "SELECT id FROM enrichment_locations WHERE shop_id=? AND entity_type=? AND entity_id=?", (shop_id, entity_type, entity_id))
    values = (
        address,
        geo.get("latitude"),
        geo.get("longitude"),
        geo.get("state_fips"),
        geo.get("county_fips"),
        geo.get("tract"),
        source,
        float(geo.get("confidence", 0)),
        _now(),
    )
    if existing:
        core.db_execute(conn, "UPDATE enrichment_locations SET address_text=?,latitude=?,longitude=?,state_fips=?,county_fips=?,tract=?,source=?,confidence=?,observed_at=? WHERE id=?", values + (existing["id"],))
        return existing["id"]
    location_id = f"geo_{uuid.uuid4().hex[:12]}"
    core.db_execute(conn, "INSERT INTO enrichment_locations(id,shop_id,entity_type,entity_id,address_text,latitude,longitude,state_fips,county_fips,tract,source,confidence,observed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (location_id, shop_id, entity_type, entity_id) + values)
    return location_id


def geocode_address(address: str):
    address = str(address or "").strip()
    if not address:
        return None
    params = urllib.parse.urlencode({"address": address, "benchmark": "Public_AR_Current", "vintage": "Current_Current", "format": "json"})
    payload = _json_get(f"{CENSUS_GEOCODER_URL}?{params}")
    matches = (((payload or {}).get("result") or {}).get("addressMatches") or [])
    if not matches:
        return None
    match = matches[0]
    coords = match.get("coordinates") or {}
    geographies = match.get("geographies") or {}
    tract_row = (geographies.get("Census Tracts") or [{}])[0]
    state_fips = str(tract_row.get("STATE") or "")
    county_fips = str(tract_row.get("COUNTY") or "")
    tract = str(tract_row.get("TRACT") or "")
    return {
        "matched_address": match.get("matchedAddress") or address,
        "latitude": float(coords["y"]),
        "longitude": float(coords["x"]),
        "state_fips": state_fips or None,
        "county_fips": county_fips or None,
        "tract": tract or None,
        "confidence": 0.95,
    }


def acs_area_context(state_fips: str, county_fips: str, tract: str):
    if not state_fips or not county_fips or not tract:
        return None
    fields = "NAME,B19013_001E,B25077_001E,B01003_001E,B23025_005E"
    params = urllib.parse.urlencode({"get": fields, "for": f"tract:{tract}", "in": f"state:{state_fips} county:{county_fips}"})
    rows = _json_get(f"{CENSUS_ACS_URL}?{params}")
    if not rows or len(rows) < 2:
        return None
    header, row = rows[0], rows[1]
    data = dict(zip(header, row))
    def number(key):
        try:
            value = float(data.get(key))
            return None if value < 0 else value
        except Exception:
            return None
    population = number("B01003_001E")
    unemployed = number("B23025_005E")
    return {
        "area_label": data.get("NAME"),
        "median_household_income": number("B19013_001E"),
        "median_home_value": number("B25077_001E"),
        "population": population,
        "unemployed_population": unemployed,
        "classification": "area_level_context_only",
        "dataset": "ACS 2024 5-year",
    }


def _haversine_miles(lat1, lon1, lat2, lon2):
    radius = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def drive_context(customer_geo, shop_geo):
    if not customer_geo or not shop_geo:
        return None
    c_lat, c_lon = customer_geo.get("latitude"), customer_geo.get("longitude")
    s_lat, s_lon = shop_geo.get("latitude"), shop_geo.get("longitude")
    if None in (c_lat, c_lon, s_lat, s_lon):
        return None
    straight = _haversine_miles(float(c_lat), float(c_lon), float(s_lat), float(s_lon))
    try:
        url = f"{OSRM_ROUTE_URL}/{c_lon},{c_lat};{s_lon},{s_lat}?overview=false&steps=false"
        payload = _json_get(url, timeout=6)
        route = (payload.get("routes") or [None])[0]
        if route:
            return {
                "drive_miles": round(float(route["distance"]) / 1609.344, 1),
                "drive_minutes": round(float(route["duration"]) / 60.0, 1),
                "straight_line_miles": round(straight, 1),
                "provider": "OSRM",
                "confidence": 0.9,
            }
    except Exception:
        pass
    return {
        "drive_miles": round(straight * 1.18, 1),
        "drive_minutes": None,
        "straight_line_miles": round(straight, 1),
        "provider": "haversine_fallback",
        "confidence": 0.55,
    }


def set_shop_location(shop_id: str, address: str, source: str = "shop_setup"):
    ensure_schema()
    geo = geocode_address(address)
    if not geo:
        return None
    conn = core.connect()
    try:
        _upsert_location(conn, shop_id, "shop", shop_id, address, geo, source)
        demand_core.record_signal(shop_id, None, "context.shop_geocode", source, {**geo, "address": address}, confidence=geo["confidence"], conn=conn)
        conn.commit()
    finally:
        conn.close()
    return geo


def enrich_customer(shop_id: str, customer_id: str, address: str, source: str = "concierge_zero_party"):
    """Geocode explicit customer location and attach ACS + drive context.

    ACS values are always nested under ``area_context`` and explicitly labeled as
    area-level so callers cannot confuse them with individual customer attributes.
    """
    import uuid
    ensure_schema()
    geo = geocode_address(address)
    if not geo:
        return None
    conn = core.connect()
    try:
        _upsert_location(conn, shop_id, "customer", customer_id, address, geo, source)
        shop_row = core.db_fetchone(conn, "SELECT * FROM enrichment_locations WHERE shop_id=? AND entity_type='shop' AND entity_id=?", (shop_id, shop_id))
        shop_geo = dict(shop_row) if shop_row else None
        area = None
        try:
            area = acs_area_context(geo.get("state_fips"), geo.get("county_fips"), geo.get("tract"))
        except Exception:
            area = None
        drive = drive_context(geo, shop_geo)
        context = {
            "geocode": {"matched_address": geo.get("matched_address"), "latitude": geo.get("latitude"), "longitude": geo.get("longitude")},
            "area_context": area or {},
            "travel": drive or {},
        }
        confidence = min(float(geo.get("confidence", 0)), float((drive or {}).get("confidence", 1.0)))
        existing = core.db_fetchone(conn, "SELECT id FROM enrichment_context WHERE shop_id=? AND customer_id=?", (shop_id, customer_id))
        if existing:
            core.db_execute(conn, "UPDATE enrichment_context SET context_json=?,source=?,confidence=?,observed_at=? WHERE id=?", (json.dumps(context), source, confidence, _now(), existing["id"]))
        else:
            core.db_execute(conn, "INSERT INTO enrichment_context(id,shop_id,customer_id,context_json,source,confidence,observed_at) VALUES(?,?,?,?,?,?,?)", (f"ctx_{uuid.uuid4().hex[:12]}", shop_id, customer_id, json.dumps(context), source, confidence, _now()))
        demand_core.record_signal(shop_id, customer_id, "context.customer_geocode", source, {"matched_address": geo.get("matched_address"), "latitude": geo.get("latitude"), "longitude": geo.get("longitude")}, confidence=geo["confidence"], conn=conn)
        if area:
            demand_core.record_signal(shop_id, customer_id, "context.acs_area", "US_Census_ACS_2024_5yr", area, confidence=0.95, conn=conn)
        if drive:
            demand_core.record_signal(shop_id, customer_id, "context.drive_time", drive.get("provider") or "routing", drive, confidence=drive.get("confidence", 0.5), conn=conn)
        conn.commit()
        return context
    finally:
        conn.close()


def customer_context(shop_id: str, customer_id: str):
    ensure_schema()
    conn = core.connect()
    try:
        row = core.db_fetchone(conn, "SELECT context_json,source,confidence,observed_at FROM enrichment_context WHERE shop_id=? AND customer_id=?", (shop_id, customer_id))
        if not row:
            return {}
        try:
            value = json.loads(row["context_json"] or "{}")
        except Exception:
            value = {}
        value["provenance"] = {"source": row["source"], "confidence": float(row["confidence"] or 0), "observed_at": row["observed_at"]}
        return value
    finally:
        conn.close()
