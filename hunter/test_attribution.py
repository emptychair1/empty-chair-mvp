from datetime import datetime, timezone

import pytest

from attribution import (
    EVENT_SCHEMA,
    REPORT_SCHEMA,
    SCHEMA,
    attribution_report,
    build_manifest,
    merge_events,
    target_id,
    tracked_link,
)

NOW = datetime(2026, 9, 6, 14, 30, tzinfo=timezone.utc)


def queue_payload():
    return {
        "schema": "empty-chair-hunter-queue-v1",
        "generated_at": NOW.isoformat(),
        "targets": [
            {
                "account_id": "acct-1",
                "username": "artist.one",
                "profile_url": "https://instagram.com/artist.one/",
                "score": 95,
                "score_state": "HOT",
                "queue_state": "HOT",
                "action_key": "ak-1",
                "signal_ids": ["sig-2", "sig-1"],
                "components": [{"rule": "explicit_cancellation", "points": 35}],
                "location": {"city": "Athens", "region": "GA", "country": "US"},
                "first_seen": NOW.isoformat(),
                "last_seen": NOW.isoformat(),
            },
            {
                "account_id": "acct-2",
                "username": "artist.two",
                "score": 70,
                "score_state": "WARM",
                "queue_state": "WARM",
                "signal_ids": ["sig-3"],
            },
        ],
    }


def event(hid, event_type, when, **extra):
    value = {
        "hunter_target_id": hid,
        "event_type": event_type,
        "occurred_at": when,
    }
    value.update(extra)
    return value


def events(*items):
    return {"schema": EVENT_SCHEMA, "events": list(items)}


def test_target_id_is_stable_and_account_specific():
    assert target_id("acct-1") == target_id("acct-1")
    assert target_id("acct-1") != target_id("acct-2")
    assert target_id("acct-1").startswith("ht_")
    with pytest.raises(ValueError):
        target_id("")


def test_tracked_link_uses_first_party_https_signup_and_hunter_id():
    hid = target_id("acct-1")
    link = tracked_link("https://app.tryemptychair.com/", hid)
    assert link.startswith("https://app.tryemptychair.com/signup?")
    assert f"hunter_target_id={hid}" in link
    assert "utm_source=hunter" in link
    with pytest.raises(ValueError):
        tracked_link("http://localhost:8000", hid)


def test_manifest_preserves_score_source_and_action_metadata():
    manifest = build_manifest(queue_payload(), base_url="https://app.tryemptychair.com", now=NOW)
    assert manifest["schema"] == SCHEMA
    assert manifest["target_count"] == 2
    first = manifest["targets"][0]
    assert first["account_id"] == "acct-1"
    assert first["signal_ids"] == ["sig-1", "sig-2"]
    assert first["action_key"] == "ak-1"
    assert first["components"][0]["rule"] == "explicit_cancellation"
    assert first["tracked_link"].startswith("https://app.tryemptychair.com/signup?")


def test_manifest_dedupes_accounts():
    payload = queue_payload()
    payload["targets"].append(dict(payload["targets"][0]))
    manifest = build_manifest(payload, base_url="https://app.tryemptychair.com", now=NOW)
    assert manifest["target_count"] == 2


def test_event_merge_dedupes_replayed_conversion():
    hid = target_id("acct-1")
    paid = event(hid, "PAID", "2026-09-06T14:40:00+00:00", entity_id="sub-1", amount_cents=9900)
    merged = merge_events(events(paid), events(paid), now=NOW)
    assert merged["event_count"] == 1
    assert merged["events"][0]["amount_cents"] == 9900


def test_explicit_event_id_is_idempotency_key():
    hid = target_id("acct-1")
    first = event(hid, "SIGNUP", "2026-09-06T14:35:00+00:00", event_id="signup-123")
    second = event(hid, "SIGNUP", "2026-09-06T14:36:00+00:00", event_id="signup-123")
    merged = merge_events(events(first), events(second), now=NOW)
    assert merged["event_count"] == 1


def test_invalid_events_are_ignored_conservatively():
    hid = target_id("acct-1")
    payload = events(
        event(hid, "NOPE", NOW.isoformat()),
        event("bad", "VISIT", NOW.isoformat()),
        event(hid, "VISIT", "not-a-date"),
        event(hid, "PAID", NOW.isoformat(), amount_cents=-1),
    )
    merged = merge_events(payload, now=NOW)
    assert merged["events"] == []


def test_report_preserves_first_and_latest_touch_and_revenue():
    manifest = build_manifest(queue_payload(), base_url="https://app.tryemptychair.com", now=NOW)
    hid = target_id("acct-1")
    payload = events(
        event(hid, "VISIT", "2026-09-06T14:31:00+00:00", entity_id="visit-1"),
        event(hid, "SIGNUP", "2026-09-06T14:32:00+00:00", entity_id="shop-1"),
        event(hid, "TRIAL", "2026-09-06T14:33:00+00:00", entity_id="shop-1"),
        event(hid, "ARMED", "2026-09-06T14:34:00+00:00", entity_id="shop-1"),
        event(hid, "PAID", "2026-09-06T14:35:00+00:00", entity_id="sub-1", amount_cents=9900, currency="usd"),
    )
    report = attribution_report(manifest, payload, now=NOW)
    assert report["schema"] == REPORT_SCHEMA
    assert report["paid_target_count"] == 1
    assert report["revenue_cents"] == 9900
    assert report["paid_conversion_rate"] == 0.5
    row = next(x for x in report["targets"] if x["account_id"] == "acct-1")
    assert row["first_touch"]["event_type"] == "VISIT"
    assert row["latest_touch"]["event_type"] == "PAID"
    assert row["furthest_stage"] == "PAID"
    assert row["revenue_cents"] == 9900


def test_multiple_payments_roll_up_to_original_target():
    manifest = build_manifest(queue_payload(), base_url="https://app.tryemptychair.com", now=NOW)
    hid = target_id("acct-1")
    payload = events(
        event(hid, "PAID", "2026-09-06T14:35:00+00:00", entity_id="inv-1", amount_cents=5000),
        event(hid, "PAID", "2026-10-06T14:35:00+00:00", entity_id="inv-2", amount_cents=5000),
    )
    report = attribution_report(manifest, payload, now=NOW)
    assert report["revenue_cents"] == 10000
    assert report["paid_target_count"] == 1
    assert report["stage_target_counts"]["PAID"] == 1


def test_payload_contracts_rejected():
    with pytest.raises(ValueError):
        build_manifest({"schema": "wrong", "targets": []}, base_url="https://app.tryemptychair.com", now=NOW)
    with pytest.raises(ValueError):
        attribution_report({"schema": "wrong", "targets": []}, None, now=NOW)
    with pytest.raises(ValueError):
        merge_events({"schema": "wrong", "events": []}, now=NOW)
