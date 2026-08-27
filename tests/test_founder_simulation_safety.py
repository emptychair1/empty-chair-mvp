import os

import pytest

from founder_simulation_safety import (
    FounderSimulationSafetyError,
    assert_founder_simulation_target,
)


def test_blindwolf_is_protected_by_name(monkeypatch):
    monkeypatch.delenv("EMPTY_CHAIR_FOUNDER_SIMULATION_SHOP_ID", raising=False)
    monkeypatch.delenv("EMPTY_CHAIR_PROTECTED_SHOP_IDS", raising=False)

    with pytest.raises(FounderSimulationSafetyError, match="Blindwolf Tattoo is protected"):
        assert_founder_simulation_target(
            "shop_blindwolf",
            "Blindwolf Tattoo",
        )


def test_blindwolf_is_protected_by_exact_shop_id(monkeypatch):
    monkeypatch.setenv(
        "EMPTY_CHAIR_PROTECTED_SHOP_IDS",
        "shop_blindwolf_live",
    )
    monkeypatch.delenv("EMPTY_CHAIR_FOUNDER_SIMULATION_SHOP_ID", raising=False)

    with pytest.raises(FounderSimulationSafetyError, match="shop_id is protected"):
        assert_founder_simulation_target(
            "shop_blindwolf_live",
            "Some Renamed Shop",
        )


def test_only_crybaby_can_be_simulation_target(monkeypatch):
    monkeypatch.delenv("EMPTY_CHAIR_FOUNDER_SIMULATION_SHOP_ID", raising=False)
    monkeypatch.delenv("EMPTY_CHAIR_PROTECTED_SHOP_IDS", raising=False)

    with pytest.raises(FounderSimulationSafetyError, match="only Crybaby Tattoos"):
        assert_founder_simulation_target(
            "shop_other",
            "Other Tattoo Studio",
        )


def test_configured_crybaby_shop_id_must_match(monkeypatch):
    monkeypatch.setenv(
        "EMPTY_CHAIR_FOUNDER_SIMULATION_SHOP_ID",
        "shop_crybaby_live",
    )
    monkeypatch.delenv("EMPTY_CHAIR_PROTECTED_SHOP_IDS", raising=False)

    with pytest.raises(FounderSimulationSafetyError, match="configured Crybaby shop_id"):
        assert_founder_simulation_target(
            "shop_crybaby_wrong",
            "Crybaby Tattoos",
        )


def test_crybaby_is_allowed_when_exact_id_matches(monkeypatch):
    monkeypatch.setenv(
        "EMPTY_CHAIR_FOUNDER_SIMULATION_SHOP_ID",
        "shop_crybaby_live",
    )
    monkeypatch.setenv(
        "EMPTY_CHAIR_PROTECTED_SHOP_IDS",
        "shop_blindwolf_live",
    )

    assert (
        assert_founder_simulation_target(
            "shop_crybaby_live",
            "Crybaby Tattoos",
        )
        == "shop_crybaby_live"
    )
