import json

import app as core
import demand_core
import enrichment_v1
import privacy_trial


def _seed_privacy_shop():
    core.init_db()
    demand_core.ensure_schema()
    enrichment_v1.ensure_schema()
    shop_id = "shop_privacy_trial"
    now = core.now_iso()
    conn = core.connect()
    try:
        core.db_execute(conn, "INSERT OR IGNORE INTO shops(id,name,created_at) VALUES(?,?,?)", (shop_id, "Private Ink", now))
        for i in range(3):
            cid = f"privacy_customer_{i}"
            core.db_execute(conn, "INSERT OR IGNORE INTO customers(id,shop_id,name,phone,email,communication_consent,appointment_count,completed_count,average_spend,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (cid, shop_id, f"Secret Name {i}", f"+1706555010{i}", f"secret{i}@example.com", 1, i + 1, i, 300, now, now))
            demand_core.sync_concierge_profile(shop_id, cid, {"styles": "traditional", "budget": "$300-600", "placement": "forearm", "timing": "this month", "short_notice": "yes", "travel": "30 miles"}, conn=conn)
            core.db_execute(conn, "INSERT OR REPLACE INTO enrichment_context(id,shop_id,customer_id,context_json,source,confidence,observed_at) VALUES(?,?,?,?,?,?,?)", (f"ctx_privacy_{i}", shop_id, cid, json.dumps({"geocode": {"matched_address": "123 Secret St", "latitude": 33.95, "longitude": -83.38}, "area_context": {"median_household_income": 65000, "classification": "area_level_context_only"}, "travel": {"drive_miles": 12.5 + i, "drive_minutes": 20 + i}}), "test", 0.9, now))
        conn.commit()
    finally:
        conn.close()
    return shop_id


def test_pseudonyms_are_stable_and_shop_scoped():
    a = privacy_trial.pseudonymous_customer_id("shop_a", "cust_1")
    b = privacy_trial.pseudonymous_customer_id("shop_a", "cust_1")
    c = privacy_trial.pseudonymous_customer_id("shop_b", "cust_1")
    assert a == b
    assert a != c
    assert "cust_1" not in a


def test_trial_rows_exclude_identity_location_and_demographics():
    shop_id = _seed_privacy_shop()
    rows = privacy_trial.pseudonymous_customer_rows(shop_id)
    assert len(rows) == 3
    serialized = json.dumps(rows).lower()
    for forbidden in ["secret name", "example.com", "+1706", "secret st", "33.95", "-83.38", "65000", "traditional"]:
        assert forbidden not in serialized
    assert all(row["drive_distance_bucket"] == "10-24mi" for row in rows)


def test_trial_snapshot_suppresses_small_aggregate_groups():
    shop_id = _seed_privacy_shop()
    snapshot = privacy_trial.trial_analytics_snapshot(shop_id, min_group_size=3)
    assert snapshot["privacy_mode"] == "trial_pseudonymous_v1"
    assert snapshot["aggregate"]["customers"] == 3
    assert snapshot["aggregate"]["drive_distance"] == {"10-24mi": 3}
    assert "name" in snapshot["excluded_fields"]
    assert "latitude" in snapshot["excluded_fields"]


def test_trial_snapshot_never_returns_raw_customer_ids():
    shop_id = _seed_privacy_shop()
    snapshot = privacy_trial.trial_analytics_snapshot(shop_id)
    body = json.dumps(snapshot)
    assert "privacy_customer_0" not in body
    assert "privacy_customer_1" not in body
    assert "privacy_customer_2" not in body
