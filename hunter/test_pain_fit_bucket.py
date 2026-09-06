from pain_fit_bucket import pain_matches, pain_score


def test_pain_matches_cancellation():
    found = pain_matches("Had a cancellation tomorrow. Spot is open.")
    assert found["disruption"]


def test_pain_matches_urgent_capacity():
    found = pain_matches("Available tomorrow for a last-minute spot")
    assert found["urgent_capacity"]


def test_generic_tattoo_post_has_no_pain():
    found = pain_matches("Fresh traditional eagle tattoo from today")
    assert not any(found.values())


def test_pain_score_meets_bucket_threshold_for_recent_capacity():
    evidence = [{"age_hours": 12, "matches": {"disruption": [], "urgent_capacity": ["available tomorrow"], "capacity": []}}]
    assert pain_score(evidence) >= 50


def test_repeated_disruption_ranks_higher():
    one = [{"age_hours": 12, "matches": {"disruption": ["cancellation"], "urgent_capacity": [], "capacity": []}}]
    two = one + [{"age_hours": 30, "matches": {"disruption": ["no-show"], "urgent_capacity": [], "capacity": []}}]
    assert pain_score(two) > pain_score(one)
