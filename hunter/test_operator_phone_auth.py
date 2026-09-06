import importlib


def load_module(monkeypatch, *, emails="", phones=""):
    monkeypatch.setenv("EMPTY_CHAIR_ADMIN_EMAILS", emails)
    monkeypatch.setenv("EMPTY_CHAIR_ADMIN_PHONES", phones)
    import v2_hunter_operator as base
    import v2_hunter_operator_phone_auth as auth
    importlib.reload(base)
    return importlib.reload(auth)


def test_email_admin_still_allowed(monkeypatch):
    auth = load_module(monkeypatch, emails="owner@example.com")
    assert auth.is_admin_artist({"email": "Owner@Example.com", "phone": "+15550000000"})


def test_phone_admin_allowed_with_normalization(monkeypatch):
    auth = load_module(monkeypatch, phones="(555) 123-4567")
    assert auth.is_admin_artist({"email": "", "phone": "+15551234567"})


def test_unknown_identity_rejected(monkeypatch):
    auth = load_module(monkeypatch, emails="owner@example.com", phones="+15551234567")
    assert not auth.is_admin_artist({"email": "other@example.com", "phone": "+15557654321"})


def test_actor_identity_uses_phone_when_email_blank(monkeypatch):
    auth = load_module(monkeypatch)
    assert auth.actor_identity({"email": "", "phone": "555-123-4567"}) == "+15551234567"
