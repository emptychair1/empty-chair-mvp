from datetime import datetime, timedelta, timezone

import app as core
import attribution_classifier
import demand_core


def _seed(prefix):
    core.init_db()
    demand_core.ensure_schema()
    now = core.now_iso()
    shop_id = f"shop_attr_{prefix}"
    customer_id = f"customer_attr_{prefix}"
    conn = core.connect()
    try:
        core.db_execute(conn, "INSERT OR IGNORE INTO shops(id,name,created_at) VALUES(?,?,?)", (shop_id, "Attribution Shop", now))
        core.db_execute(conn, "INSERT OR IGNORE INTO customers(id,shop_id,name,phone,email,communication_consent,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (customer_id, shop_id, "Attribution Customer", "+17065550999", "attr@example.com", 1, now, now))
        conn.commit()
    finally:
        conn.close()
    return shop_id, customer_id


def _at(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_same_opening_claim_is_direct():
    shop_id, customer_id = _seed("direct")
    demand_core.record_attribution(shop_id, customer_id, "opening_direct", "offer_sent", channel="sms", observed_at if False else None)
    demand_core.record_attribution(shop_id, customer_id, "opening_direct", "offer_claimed", channel="sms", attribution_class="direct")
    result = attribution_classifier.classify_outcome(shop_id, customer_id, "opening_direct")
    assert result["class"] == "direct"
    assert result["reason"] == "same_opening_offer_claim"


def test_recent_other_intervention_is_assisted():
    shop_id, customer_id = _seed("assisted")
    demand_core.record_attribution(shop_id, customer_id, "opening_offer", "offer_sent", channel="sms", attribution_class="candidate")
    result = attribution_classifier.classify_outcome(shop_id, customer_id, "opening_booked")
    assert result["class"] == "assisted"
    assert result["reason"] == "recent_empty_chair_intervention"


def test_no_recent_intervention_is_organic():
    shop_id, customer_id = _seed("organic")
    result = attribution_classifier.classify_outcome(shop_id, customer_id, "opening_booked")
    assert result["class"] == "organic"
    assert result["reason"] == "no_recent_empty_chair_intervention"


def test_intervention_outside_lookback_does_not_get_credit():
    shop_id, customer_id = _seed("old")
    conn = core.connect()
    try:
        demand_core.record_attribution(shop_id, customer_id, "opening_old", "offer_sent", channel="sms", attribution_class="candidate", conn=conn)
        core.db_execute(conn, "UPDATE attribution_events SET created_at=? WHERE shop_id=? AND customer_id=? AND action_type='offer_sent'", (_at(45), shop_id, customer_id))
        conn.commit()
    finally:
        conn.close()
    result = attribution_classifier.classify_outcome(shop_id, customer_id, "opening_new", lookback_days=30)
    assert result["class"] == "organic"


def test_record_booking_outcome_writes_classification_into_signal():
    shop_id, customer_id = _seed("record")
    demand_core.record_attribution(shop_id, customer_id, "opening_record", "offer_claimed", channel="sms", attribution_class="direct")
    result = attribution_classifier.record_booking_outcome(shop_id, customer_id, "opening_record", "booking_record", "artist_record", 500)
    assert result["class"] == "direct"
    intel = demand_core.customer_intelligence(shop_id, customer_id)
    booking_events = [e for e in intel["attribution"] if e["action_type"] == "booking_confirmed"]
    assert booking_events[-1]["attribution_class"] == "direct"
    assert booking_events[-1]["metadata"]["classification_reason"] == "same_opening_offer_claim"
    assert any(s["signal_type"] == "outcome.booking_confirmed" and s["value"].get("attribution_class") == "direct" for s in intel["provenance"])
