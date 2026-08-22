import json

import app as core
import demand_core
import enrichment_v1


def _shop_customer(prefix="dc"):
    core.init_db()
    demand_core.ensure_schema()
    now = core.now_iso()
    shop_id = f"shop_{prefix}"
    customer_id = f"cust_{prefix}"
    conn = core.connect()
    try:
        core.db_execute(conn, "INSERT OR IGNORE INTO shops(id,name,created_at) VALUES(?,?,?)", (shop_id, "Demand Core Test", now))
        core.db_execute(conn, "INSERT OR IGNORE INTO customers(id,shop_id,name,phone,email,communication_consent,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (customer_id, shop_id, "DNA Customer", "+17065550000", "dna@example.com", 1, now, now))
        conn.commit()
    finally:
        conn.close()
    return shop_id, customer_id


def test_concierge_profile_becomes_provenance_and_practical_fit():
    shop_id, customer_id = _shop_customer("profile")
    profile = {"styles": "black and grey, botanical", "placement": "forearm", "budget": "$600-1000", "timing": "this month", "short_notice": "yes", "travel": "30 miles", "location": "Athens, GA", "offer_opt_in": True}
    demand_core.capture_concierge_profile(shop_id, customer_id, profile)
    demand_core.sync_concierge_profile(shop_id, customer_id, profile)
    intel = demand_core.customer_intelligence(shop_id, customer_id)
    assert "black and grey" in intel["visual"]["styles"]
    assert intel["practical"]["placement"] == "forearm"
    assert any(s["signal_type"] == "declared.budget" and s["source"] == "concierge_zero_party" for s in intel["provenance"])
    assert any(s["signal_type"] == "declared.location" and s["source"] == "concierge_zero_party" for s in intel["provenance"])


def test_customer_intelligence_exposes_contextual_enrichment():
    shop_id, customer_id = _shop_customer("context")
    enrichment_v1.ensure_schema()
    now = core.now_iso()
    context = {
        "geocode": {"matched_address": "Athens, GA"},
        "area_context": {"classification": "area_level_context_only", "median_household_income": 60000},
        "travel": {"drive_miles": 8.2, "drive_minutes": 14.0},
    }
    conn = core.connect()
    try:
        core.db_execute(conn, "INSERT OR REPLACE INTO enrichment_context(id,shop_id,customer_id,context_json,source,confidence,observed_at) VALUES(?,?,?,?,?,?,?)", ("ctx_test", shop_id, customer_id, json.dumps(context), "test_enrichment", 0.9, now))
        conn.commit()
    finally:
        conn.close()
    intel = demand_core.customer_intelligence(shop_id, customer_id)
    assert intel["contextual"]["travel"]["drive_minutes"] == 14.0
    assert intel["contextual"]["area_context"]["classification"] == "area_level_context_only"
    assert intel["contextual"]["provenance"]["source"] == "test_enrichment"


def test_customer_intelligence_is_shop_scoped():
    shop_id, customer_id = _shop_customer("scope")
    assert demand_core.customer_intelligence(shop_id, customer_id) is not None
    assert demand_core.customer_intelligence("some_other_shop", customer_id) is None


def test_attribution_round_trip():
    shop_id, customer_id = _shop_customer("attr")
    event_id = demand_core.record_attribution(shop_id, customer_id, None, "offer_sent", channel="sms", metadata={"offer_id": "offer_test"})
    assert event_id
    intel = demand_core.customer_intelligence(shop_id, customer_id)
    assert any(a["action_type"] == "offer_sent" and a["metadata"]["offer_id"] == "offer_test" for a in intel["attribution"])
