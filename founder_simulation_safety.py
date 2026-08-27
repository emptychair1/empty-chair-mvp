"""Safety guardrails for founder-only M4 simulation resets.

The founder simulator is allowed to mutate Crybaby Tattoos test data only.
Blindwolf Tattoo is explicitly protected, including Concierge leads and the
customer records attached to those leads.
"""

import os


CRYBABY_SHOP_NAMES = {
    "crybaby tattoos",
    "crybaby tattoo",
}

PROTECTED_SHOP_NAMES = {
    "blindwolf tattoo",
    "blind wolf tattoo",
    "blindwolf tattoos",
    "blind wolf tattoos",
}


class FounderSimulationSafetyError(RuntimeError):
    """Raised when a founder simulation reset targets an unsafe shop."""


def _normalize_name(value):
    return " ".join(str(value or "").strip().lower().split())


def _configured_ids(env_name):
    return {
        item.strip()
        for item in os.getenv(env_name, "").split(",")
        if item.strip()
    }


def assert_founder_simulation_target(shop_id, shop_name):
    """Verify a reset target is Crybaby and is not explicitly protected.

    Exact IDs can be pinned in production with:
      EMPTY_CHAIR_FOUNDER_SIMULATION_SHOP_ID
      EMPTY_CHAIR_PROTECTED_SHOP_IDS

    Name checks remain in place as a second independent safety layer.
    """
    shop_id = str(shop_id or "").strip()
    normalized_name = _normalize_name(shop_name)

    if not shop_id:
        raise FounderSimulationSafetyError(
            "Founder simulation reset refused: target shop_id is required."
        )

    protected_ids = _configured_ids("EMPTY_CHAIR_PROTECTED_SHOP_IDS")
    if shop_id in protected_ids:
        raise FounderSimulationSafetyError(
            "Founder simulation reset refused: target shop_id is protected."
        )

    if normalized_name in PROTECTED_SHOP_NAMES:
        raise FounderSimulationSafetyError(
            "Founder simulation reset refused: Blindwolf Tattoo is protected."
        )

    configured_target = os.getenv(
        "EMPTY_CHAIR_FOUNDER_SIMULATION_SHOP_ID",
        "",
    ).strip()

    if configured_target and shop_id != configured_target:
        raise FounderSimulationSafetyError(
            "Founder simulation reset refused: target does not match the configured Crybaby shop_id."
        )

    if normalized_name not in CRYBABY_SHOP_NAMES:
        raise FounderSimulationSafetyError(
            "Founder simulation reset refused: only Crybaby Tattoos may be reset."
        )

    return shop_id


def load_and_assert_founder_simulation_target(conn, db_fetchone, shop_id):
    """Load the shop record and apply all reset protections before mutation."""
    shop = db_fetchone(
        conn,
        "SELECT id,name FROM shops WHERE id=?",
        (shop_id,),
    )

    if not shop:
        raise FounderSimulationSafetyError(
            "Founder simulation reset refused: target shop does not exist."
        )

    return assert_founder_simulation_target(
        shop["id"],
        shop["name"],
    )
