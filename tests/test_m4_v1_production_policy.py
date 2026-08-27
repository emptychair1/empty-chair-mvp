from datetime import datetime, timedelta, timezone

import m4_integration


def opening(price=450):
    dt = datetime.now(timezone.utc) + timedelta(days=1)
    return {
        "id": "open_test",
        "shop_id": "shop_test",
        "artist_id": "artist_test",
        "date": dt.date().isoformat(),
        "start_time": dt.strftime("%H:%M"),
        "price": price,
        "style": "traditional",
    }


def customer():
    return {
        "id": "customer_test",
        "shop_id": "shop_test",
        "name": "Test Customer",
        "communication_consent": 1,
        "preferred_styles": "traditional",
        "preferred_artists": "artist_test",
        "average_spend": 500,
        "completed_count": 3,
        "cancellation_count": 0,
        "no_show_count": 0,
    }


def test_frozen_v1_probability_requires_budget_and_distance():
    c = customer()
    o = opening()
    assert m4_integration._trained_v1_probability(
        c, o, 0.55, 1.0, 1.0, None, 1.0, 1.0
    ) is None
    assert m4_integration._trained_v1_probability(
        c, o, 0.55, 1.0, 1.0, 1.0, None, 1.0
    ) is None


def test_frozen_v1_probability_is_bounded_when_required_evidence_exists():
    p = m4_integration._trained_v1_probability(
        customer(), opening(), 0.55, 1.0, 1.0, 0.95, 0.90, 1.0
    )
    assert p is not None
    assert 0.0 < p < 1.0


def test_frozen_model_is_the_passed_artifact():
    assert m4_integration.FROZEN_V1_VERSION == "m4-v1-fast-train-1-frozen"
    assert m4_integration.FROZEN_V1["status"] == "FROZEN_AFTER_UNTOUCHED_PASS"
    evaluation = m4_integration.FROZEN_V1["final_untouched_evaluation"]
    assert evaluation["top1_lift"] >= 0.07
    assert evaluation["top3_lift"] >= 0.04
    assert evaluation["fill_delta"] == 0.0
