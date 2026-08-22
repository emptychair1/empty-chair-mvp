import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

TEST_DB = Path("test_empty_chair.db")
os.environ["EMPTY_CHAIR_DB"] = str(TEST_DB)
os.environ["EMPTY_CHAIR_DEMO_MODE"] = "true"
os.environ["EMPTY_CHAIR_SESSION_SECRET"] = "test-secret"
os.environ["EMPTY_CHAIR_WORKER_ENABLED"] = "false"
os.environ.pop("DATABASE_URL", None)

from bootstrap import app
import delivery_safety
import demand_core
import demand_engine
import enrichment_v1
import google_integration
import m4_integration

core = sys.modules["empty_chair_legacy_app"]


@pytest.fixture(autouse=True)
def fresh_database():
    if TEST_DB.exists():
        TEST_DB.unlink()
    core.init_db()
    demand_core.ensure_schema()
    enrichment_v1.ensure_schema()
    delivery_safety.ensure_schema()
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()


def _signup(client):
    response = client.post(
        "/signup",
        data={
            "name": "Pipeline Owner",
            "shop_name": "Pipeline Tattoo Studio",
            "email": "pipeline-owner@example.com",
            "password": "testing123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT id FROM shops WHERE name=?", ("Pipeline Tattoo Studio",))
    finally:
        conn.close()
    assert shop
    return shop["id"]


def _fake_geocode(address):
    if "shop" in str(address or "").lower():
        return {
            "matched_address": "100 Shop St, Athens, GA 30601",
            "latitude": 33.9600,
            "longitude": -83.3770,
            "state_fips": "13",
            "county_fips": "059",
            "tract": "000100",
            "zcta": None,
            "geography_level": "tract",
            "confidence": 0.95,
        }
    return {
        "matched_address": "30601, Athens, GA",
        "latitude": 33.9519,
        "longitude": -83.3576,
        "state_fips": None,
        "county_fips": None,
        "tract": None,
        "zcta": "30601",
        "geography_level": "zip",
        "confidence": 0.82,
    }


def _fake_acs(*args, **kwargs):
    return {
        "area_label": "ZCTA5 30601",
        "median_household_income": 62000.0,
        "median_home_value": 245000.0,
        "population": 21000.0,
        "unemployed_population": 500.0,
        "classification": "area_level_context_only",
        "geography_level": "zcta",
        "dataset": "ACS 2024 5-year",
    }


def _fake_drive(customer_geo, shop_geo):
    return {
        "drive_miles": 4.8,
        "drive_minutes": 11.0,
        "straight_line_miles": 4.1,
        "provider": "test-routing",
        "confidence": 0.9,
    }


def _fake_vision(image_bytes, mime_type, subject="customer inspiration"):
    return {
        "status": "analyzed",
        "styles": ["traditional"],
        "motifs": ["rose"],
        "palette": ["red", "black"],
        "line_weight": "bold",
        "composition": "centered",
        "likely_scale": "medium",
        "likely_placement": ["forearm", "upper arm"] if "artist" in subject else ["forearm"],
        "confidence": 0.92 if "artist" in subject else 0.94,
        "summary": "Bold traditional rose portfolio work." if "artist" in subject else "Traditional rose inspiration with bold lines.",
    }


def test_full_concierge_to_learning_pipeline(monkeypatch):
    monkeypatch.setattr(enrichment_v1, "geocode_address", _fake_geocode)
    monkeypatch.setattr(enrichment_v1, "acs_area_context", _fake_acs)
    monkeypatch.setattr(enrichment_v1, "drive_context", _fake_drive)
    monkeypatch.setattr(demand_engine, "_vision_analyze", _fake_vision)

    with TestClient(app) as client:
        shop_id = _signup(client)
        enrichment_v1.set_shop_location(shop_id, "100 Shop St, Athens, GA 30601")

        now = core.now_iso()
        artist_id = "artist_pipeline"
        conn = core.connect()
        try:
            core.db_execute(
                conn,
                "INSERT INTO artists(id,shop_id,name,styles,services,active) VALUES(?,?,?,?,?,1)",
                (artist_id, shop_id, "Alex Traditional", "traditional", "tattoo"),
            )
            conn.commit()
        finally:
            conn.close()

        profile = client.post(
            "/api/concierge/profile",
            data={
                "shop_id": shop_id,
                "session_id": "session_pipeline",
                "name": "Pipeline Customer",
                "email": "pipeline-customer@example.com",
                "phone": "+17065550123",
                "contact_preference": "sms",
                "offer_consent": "yes",
                "project": "Traditional rose on my forearm",
                "styles": "traditional",
                "placement": "forearm",
                "budget": "$300–600",
                "timing": "This week",
                "short_notice": "Yes — I can move fast",
                "artist_vibe": "Alex Traditional",
                "travel": "15 miles",
                "location": "30601",
            },
        )
        assert profile.status_code == 200, profile.text
        profile_json = profile.json()
        customer_id = profile_json["customer_id"]
        assert profile_json["communication_consent"] is True
        assert profile_json["contextual_enrichment"]["travel"]["drive_miles"] == 4.8

        inspiration = client.post(
            "/api/concierge/inspiration",
            data={"shop_id": shop_id, "session_id": "session_pipeline"},
            files={"image": ("rose.png", b"fake-image-bytes", "image/png")},
        )
        assert inspiration.status_code == 200, inspiration.text
        token = inspiration.json()["attach_token"]
        attached = client.post(
            "/api/concierge/inspiration/attach",
            json={"shop_id": shop_id, "session_id": "session_pipeline", "customer_id": customer_id, "tokens": [token]},
        )
        assert attached.status_code == 200, attached.text
        assert attached.json()["tattoo_dna"]["styles"] == ["traditional"]

        portfolio = client.post(
            f"/api/demand-graph/artist/{artist_id}/portfolio",
            files={"image": ("artist-rose.png", b"fake-portfolio-bytes", "image/png")},
        )
        assert portfolio.status_code == 200, portfolio.text
        assert "traditional" in portfolio.json()["artist_dna"]["styles"]

        opening_date = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
        expires_at = (datetime.now(timezone.utc) + timedelta(days=2, hours=1)).isoformat()
        opening_id = "opening_pipeline"
        conn = core.connect()
        try:
            core.db_execute(
                conn,
                "INSERT INTO openings(id,shop_id,artist_id,date,start_time,end_time,service,price,status,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (opening_id, shop_id, artist_id, opening_date, "14:00", "16:00", "tattoo", 450, "OPEN", now, expires_at),
            )
            conn.commit()
            customer = core.db_fetchone(conn, "SELECT * FROM customers WHERE id=?", (customer_id,))
            opening = core.db_fetchone(conn, "SELECT * FROM openings WHERE id=?", (opening_id,))
            artist = core.db_fetchone(conn, "SELECT * FROM artists WHERE id=?", (artist_id,))
        finally:
            conn.close()

        breakdown = m4_integration.m4_recovery_breakdown(customer, opening, artist)
        assert breakdown["tattoo_dna_match"] == 1.0
        assert breakdown["budget_fit"] == 1.0
        assert breakdown["placement_fit"] == 1.0
        assert breakdown["distance_fit"] == 1.0
        assert breakdown["practical_score"] is not None
        assert any("Tattoo DNA × Artist DNA" in reason for reason in breakdown["why"])

        with patch.object(google_integration, "calendar_user_for_artist", return_value=None):
            core.start_recovery_campaign(opening_id)

        conn = core.connect()
        try:
            offer = core.db_fetchone(
                conn,
                "SELECT * FROM offers WHERE opening_id=? AND customer_id=? ORDER BY rank LIMIT 1",
                (opening_id, customer_id),
            )
        finally:
            conn.close()
        assert offer
        assert offer["status"] == "SENT"
        assert float(offer["score"]) > 0

        with patch.object(google_integration, "calendar_user_for_artist", return_value=None):
            claimed = client.post(f"/offer/{offer['id']}/claim", follow_redirects=False)
        assert claimed.status_code in (302, 303), claimed.text

        conn = core.connect()
        try:
            booking = core.db_fetchone(conn, "SELECT * FROM bookings WHERE opening_id=?", (opening_id,))
        finally:
            conn.close()
        assert booking
        assert booking["status"] in ("AWAITING_CONFIRMATION", "PENDING")

        with patch.object(google_integration, "calendar_user_for_artist", return_value=None):
            confirmed = client.post(f"/bookings/{booking['id']}/confirm", follow_redirects=False)
        assert confirmed.status_code in (302, 303), confirmed.text

        conn = core.connect()
        try:
            final_booking = core.db_fetchone(conn, "SELECT status FROM bookings WHERE id=?", (booking["id"],))
            final_opening = core.db_fetchone(conn, "SELECT status FROM openings WHERE id=?", (opening_id,))
        finally:
            conn.close()
        assert final_booking["status"] == "CONFIRMED"
        assert final_opening["status"] == "BOOKED"

        intelligence = demand_core.customer_intelligence(shop_id, customer_id)
        action_types = [event["action_type"] for event in intelligence["attribution"]]
        assert "offer_sent" in action_types
        assert "offer_claimed" in action_types
        assert "booking_confirmed" in action_types

        confirmed_events = [event for event in intelligence["attribution"] if event["action_type"] == "booking_confirmed"]
        assert confirmed_events[-1]["attribution_class"] == "direct"
        assert confirmed_events[-1]["metadata"]["classification_reason"] == "same_opening_offer_claim"

        outcome_signals = [signal for signal in intelligence["provenance"] if signal["signal_type"] == "outcome.booking_confirmed"]
        assert outcome_signals
        assert outcome_signals[-1]["value"]["attribution_class"] == "direct"

        contextual_signals = {signal["signal_type"] for signal in intelligence["provenance"]}
        assert "context.customer_geocode" in contextual_signals
        assert "context.acs_area" in contextual_signals
        assert "context.drive_time" in contextual_signals
