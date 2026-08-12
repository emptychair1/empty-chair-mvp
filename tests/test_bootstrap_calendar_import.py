def test_calendar_safety_is_registered():
    import bootstrap
    import calendar_safety

    assert bootstrap.core.start_recovery_campaign is calendar_safety.start_recovery_campaign_calendar_safe
