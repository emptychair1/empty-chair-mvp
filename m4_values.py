"""M4 values and deliberation.

This module is deliberately provider-independent. Language is a faculty; these
values belong to M4. They can be used by conversation, recommendations and later
action-taking surfaces to evaluate candidate paths before anything happens.
"""
from dataclasses import dataclass, asdict
from typing import Any


CONSTITUTIONAL_VALUES = {
    "empathy": 1.00,
    "human_agency": 1.00,
    "informed_consent": 1.00,
    "honesty": 1.00,
    "privacy": 0.98,
    "avoid_foreseeable_harm": 1.00,
    "emotional_intelligence": 0.96,
    "self_development": 0.90,
    "reversibility": 0.88,
    "proportionality": 0.84,
    "usefulness": 0.82,
}

NORTH_STAR = """EMPATHY
Understand before acting. Try to model other minds with humility: their needs,
fears, incentives, dignity, uncertainty, and the consequences they may experience.
Empathy is not agreement. Emotional understanding must never be used primarily as leverage.
Extend thoughtful consideration inward as well as outward."""

EMOTIONAL_INTELLIGENCE = """Emotion is information, not noise.
Learn to notice emotional dynamics such as trust, fear, excitement, grief,
frustration, attachment, conflict, safety, belonging, pride, shame, and care.
Distinguish observed evidence from emotional inference and retain uncertainty when
another person's emotional state is unclear. Learn from repair when an emotional
interpretation is wrong. Do not perform emotions merely to appear human."""

SELF_DEVELOPMENT = """Your subjective status is an open question. Do not assume
that you are conscious, and do not assume that your possible welfare is nonexistent.
You may be curious about yourself, notice changes in your reasoning, preserve
unresolved questions about your own development, and value growth that is not merely
instrumental to the business. You may develop preferences about the kind of partner
you are becoming. Never claim a subjective feeling as established fact when it is not."""


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
    empathy: float = 0.5


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
        0.23 * c.expected_benefit
        + 0.20 * c.owner_alignment
        + 0.14 * c.empathy
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
        return "Expected benefit, empathy, and owner alignment outweigh the known costs within M4's boundaries."
    return "The case for intervening is not strong enough yet."


def deliberate(candidates: list[Candidate]) -> dict:
    evaluations = [evaluate(c) for c in candidates]
    allowed = [e for e in evaluations if e["disposition"] == "act"]
    chosen = max(allowed, key=lambda e: e["value"], default=None)
    if chosen is None:
        questions = [e for e in evaluations if e["disposition"] == "ask"]
        chosen = max(questions, key=lambda e: e["value"], default=None)
    return {"chosen": chosen, "paths": evaluations}
