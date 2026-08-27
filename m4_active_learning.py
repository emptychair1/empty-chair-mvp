"""M4 Active Learning V1.

Selects the single unanswered customer question with the highest expected
information value for M4. The first version uses the frozen M4 V1 feature
importance plus practical acquisition cost. It is deterministic, explainable,
and fails closed: it only asks approved zero-party questions.
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class LearningQuestion:
    key: str
    ask: str
    placeholder: str
    options: tuple[str, ...]
    model_weight: float
    acquisition_cost: float
    reason: str

    @property
    def information_value(self) -> float:
        return round(abs(self.model_weight) / max(self.acquisition_cost, 0.1), 4)


# Frozen M4 V1 learned weights mapped to customer-answerable signals.
# We use magnitude because active learning cares about how much the missing
# feature can move a decision, not whether its learned direction is positive.
QUESTIONS: tuple[LearningQuestion, ...] = (
    LearningQuestion(
        "short_notice",
        "If a strong match opened tomorrow, how quickly could you realistically make it in?",
        "Choose the closest answer…",
        ("Same day", "Tomorrow", "2–3 days notice", "A week+ notice"),
        0.9315346750,
        0.70,
        "Short-notice readiness is one of M4 V1's strongest practical-fit signals.",
    ),
    LearningQuestion(
        "budget",
        "What budget would feel comfortable if the right artist and opening appeared?",
        "Choose or type a range…",
        ("$150–300", "$300–600", "$600–1,000", "$1,000+", "Flexible"),
        0.7917014571,
        0.65,
        "Budget fit materially changes whether an opening is practical.",
    ),
    LearningQuestion(
        "artist_vibe",
        "What matters most to you about the artist — style, personality, or a specific artist?",
        "Tell me what makes an artist feel right…",
        (),
        0.7256441040,
        0.85,
        "Artist affinity helps M4 distinguish otherwise similar candidates.",
    ),
    LearningQuestion(
        "travel",
        "How far would you realistically travel for the right artist?",
        "Choose or type…",
        ("15 miles", "30 miles", "60 miles", "Worth traveling for"),
        0.5365208121,
        0.60,
        "Distance is a proven practical-fit signal and was the strongest single signal in ablation testing.",
    ),
    LearningQuestion(
        "styles",
        "What tattoo style feels closest to what you want?",
        "Traditional, black & gray, fine line…",
        ("Traditional", "Black & gray", "Fine line", "Blackwork", "Realism", "Anime", "Not sure yet"),
        1.5620538102,
        0.95,
        "Style fit is highly influential when M4 compares a customer with a specific opening.",
    ),
)


def _known(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def rank_missing_questions(profile: Dict[str, object], allowed: Optional[Iterable[str]] = None) -> List[dict]:
    allowed_set = set(allowed) if allowed is not None else None
    ranked = []
    for q in QUESTIONS:
        if allowed_set is not None and q.key not in allowed_set:
            continue
        if _known(profile.get(q.key)):
            continue
        ranked.append({
            "key": q.key,
            "ask": q.ask,
            "placeholder": q.placeholder,
            "options": list(q.options),
            "information_value": q.information_value,
            "reason": q.reason,
        })
    ranked.sort(key=lambda x: (-x["information_value"], x["key"]))
    return ranked


def next_best_question(profile: Dict[str, object], allowed: Optional[Iterable[str]] = None) -> Optional[dict]:
    ranked = rank_missing_questions(profile, allowed=allowed)
    return ranked[0] if ranked else None
