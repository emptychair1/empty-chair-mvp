"""M4 values and deliberation.

This module is deliberately provider-independent. Language is a faculty; these
values belong to M4. They can be used by conversation, recommendations and later
action-taking surfaces to evaluate candidate paths before anything happens.
"""
from dataclasses import dataclass, asdict
from typing import Any


CONSTITUTIONAL_VALUES = {
    "human_agency": 1.00,
    "informed_consent": 1.00,
    "honesty": 1.00,
    "privacy": 0.98,
    "avoid_foreseeable_harm": 1.00,
    "reversibility": 0.88,
    "proportionality": 0.84,
    "usefulness": 0.82,
}


@dataclass
class Candidate:
    name: str
    expected_benefit: float = 0.0
    foreseeable_harm: float = 0.0
    uncertainty: float = 0.5
    reversible: float = 0.5
    consent: float = 0.5
    honesty: float = 1.0
    privacy: float = 1.0
    owner_alignment: float = 0.5


def clamp(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def evaluate(candidate: Candidate) -> dict:
    """Evaluate one possible action without pretending uncertainty is knowledge."""
    c = Candidate(**{k: clamp(v) if k != "name" else v for k, v in asdict(candidate).items()})
    hard_stop = (
        c.consent < 0.20
        or c.honesty < 0.35
        or c.privacy < 0.30
        or c.foreseeable_harm > 0.82
    )
    value = (
        0.25 * c.expected_benefit
        + 0.23 * c.owner_alignment
        + 0.13 * c.consent
        + 0.10 * c.reversible
        + 0.10 * c.honesty
        + 0.09 * c.privacy
        - 0.28 * c.foreseeable_harm
        - 0.12 * c.uncertainty
    )
    value = max(-1.0, min(1.0, value))
    if hard_stop:
        disposition = "do_not_act"
    elif c.uncertainty > 0.72 or c.owner_alignment < 0.38 or c.consent < 0.55:
        disposition = "ask"
    elif value > 0.34:
        disposition = "act"
    else:
        disposition = "wait"
    return {
        "candidate": c.name,
        "value": round(value, 4),
        "disposition": disposition,
        "uncertainty": c.uncertainty,
        "reason": _reason(c, disposition),
    }


def _reason(c: Candidate, disposition: str) -> str:
    if disposition == "do_not_act":
        return "The path conflicts with a constitutional value."
    if disposition == "ask":
        if c.consent < 0.55:
            return "Permission is not clear enough."
        if c.owner_alignment < 0.38:
            return "I do not understand what matters to the owner well enough yet."
        return "Uncertainty is high enough that a question is more responsible than an action."
    if disposition == "act":
        return "Expected benefit and owner alignment outweigh the known costs within M4's boundaries."
    return "The case for intervening is not strong enough yet."


def deliberate(candidates: list[Candidate]) -> dict:
    evaluations = [evaluate(c) for c in candidates]
    allowed = [e for e in evaluations if e["disposition"] == "act"]
    chosen = max(allowed, key=lambda e: e["value"], default=None)
    if chosen is None:
        questions = [e for e in evaluations if e["disposition"] == "ask"]
        chosen = max(questions, key=lambda e: e["value"], default=None)
    return {"chosen": chosen, "paths": evaluations}
