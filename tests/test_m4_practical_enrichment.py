from datetime import datetime, timedelta, timezone

import enrichment_v1
import m4_integration


def future_opening(days=2, price=400):
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return {
        "date": dt.date().isoformat(),
        "start_time": dt.strftime("%H:%M"),
        "price": price,
    }


def test_budget_fit_rewards_declared_range_and_penalizes_over_budget():
    assert m4_integration._budget_fit("$300–600", 450) == 1.0
    assert m4_integration._budget_fit("$300–600", 900) < 0.5
    assert m4_integration._budget_fit("Flexible", 500) is None


def test_short_notice_fit_uses_actual_opening_time():
    opening = future_opening(days=1)
    fast = m4_integration._short_notice_fit("Yes — I can move fast", opening)
    planner = m4_integration._short_notice_fit("No — I need to plan ahead", opening)
    assert fast == 1.0
    assert planner < fast


def test_timing_fit_respects_declared_window():
    soon = future_opening(days=3)
    later = future_opening(days=45)
    assert m4_integration._timing_fit("This week", soon) > m4_integration._timing_fit("This week", later)


def test_distance_fit_uses_drive_miles_not_acs_demographics():
    context = {
        "customer": {
            "travel": {"drive_miles": 22.0, "drive_minutes": 31.0},
            "area_context": {"median_household_income": 999999},
        }
    }
    assert m4_integration._distance_fit("30 miles", context) == 1.0
    assert m4_integration._distance_fit("15 miles", context) < 1.0


def test_placement_fit_uses_artist_portfolio_evidence():
    context = {"artist": {"placements": ["forearm", "upper arm", "thigh"]}}
    assert m4_integration._placement_fit("forearm", context) == 1.0
    assert m4_integration._placement_fit("calf", context) == 0.35


def test_drive_context_falls_back_without_routing(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("routing unavailable")

    monkeypatch.setattr(enrichment_v1, "_json_get", fail)
    customer = {"latitude": 33.9519, "longitude": -83.3576}
    shop = {"latitude": 33.9609, "longitude": -83.3773}
    result = enrichment_v1.drive_context(customer, shop)
    assert result["provider"] == "haversine_fallback"
    assert result["drive_miles"] > 0
    assert result["confidence"] == 0.55


def test_acs_context_is_explicitly_area_level(monkeypatch):
    monkeypatch.setattr(
        enrichment_v1,
        "_json_get",
        lambda *args, **kwargs: [
            ["NAME", "B19013_001E", "B25077_001E", "B01003_001E", "B23025_005E", "state", "county", "tract"],
            ["Census Tract 1", "65000", "250000", "4200", "100", "13", "059", "000100"],
        ],
    )
    context = enrichment_v1.acs_area_context("13", "059", "000100")
    assert context["classification"] == "area_level_context_only"
    assert context["median_household_income"] == 65000.0
