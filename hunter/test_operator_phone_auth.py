from hunter.operator_auth import (
    actor_identity,
    is_admin_identity,
    normalize_phone,
    parse_emails,
    parse_phones,
)


def test_email_admin_still_allowed():
    assert is_admin_identity(
        {"email": "Owner@Example.com", "phone": "+15550000000"},
        admin_emails=parse_emails("owner@example.com"),
        admin_phones=set(),
    )


def test_phone_admin_allowed_with_normalization():
    assert is_admin_identity(
        {"email": "", "phone": "+15551234567"},
        admin_emails=set(),
        admin_phones=parse_phones("(555) 123-4567"),
    )


def test_unknown_identity_rejected():
    assert not is_admin_identity(
        {"email": "other@example.com", "phone": "+15557654321"},
        admin_emails=parse_emails("owner@example.com"),
        admin_phones=parse_phones("+15551234567"),
    )


def test_actor_identity_uses_phone_when_email_blank():
    assert actor_identity({"email": "", "phone": "555-123-4567"}) == "+15551234567"


def test_normalize_phone_matches_production_us_rules():
    assert normalize_phone("5551234567") == "+15551234567"
    assert normalize_phone("1 (555) 123-4567") == "+15551234567"
