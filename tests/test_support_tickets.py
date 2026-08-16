import support_tickets


def test_trello_requires_all_three_settings(monkeypatch):
    for key in (
        "TRELLO_API_KEY",
        "TRELLO_API_TOKEN",
        "TRELLO_SUPPORT_LIST_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    assert support_tickets.trello_is_configured() is False

    monkeypatch.setenv("TRELLO_API_KEY", "key")
    monkeypatch.setenv("TRELLO_API_TOKEN", "token")
    monkeypatch.setenv("TRELLO_SUPPORT_LIST_ID", "list")

    assert support_tickets.trello_is_configured() is True


def test_create_trello_card_is_safe_before_setup(monkeypatch):
    for key in (
        "TRELLO_API_KEY",
        "TRELLO_API_TOKEN",
        "TRELLO_SUPPORT_LIST_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    assert support_tickets.create_trello_card(
        {
            "id": "ticket_123",
            "subject": "Calendar is not syncing",
            "category": "Calendar",
            "priority": "High",
            "description": "A test description long enough to submit.",
        },
        {
            "id": "user_123",
            "name": "Test Owner",
            "email": "owner@example.com",
        },
        {
            "id": "shop_123",
            "name": "Test Studio",
        },
    ) is None
