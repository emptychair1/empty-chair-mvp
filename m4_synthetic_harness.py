"""Deterministic regression harness for M4 prospect meetings.

This module does not require a human, microphone, browser, or model API. It replays
adversarial prospect instructions through a small meeting-state controller and scores
transcripts/event traces against acceptance criteria learned from real meetings.

The live model remains stochastic; this harness verifies the architecture around it:
behavioral state, evidence boundaries, proof requirements, reconnect continuity,
generation ownership, transcription assembly, and observability completeness.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Iterable

LEAD_TRIGGERS = (
    "take over",
    "show me",
    "prove it",
    "stop asking",
    "don't ask",
    "do not ask",
    "you tell me",
    "don't make me lead",
    "do not make me lead",
    "start talking about solutions",
    "just start talking about solutions",
)

PROOF_TRIGGERS = (
    "prove it",
    "prove that",
    "show me what you would actually do",
    "use synthetic data",
    "make up some data",
    "synthetic data",
)

SALES_REJECTION_TRIGGERS = (
    "sales pitch",
    "pitching me",
    "stop pitching",
    "snake oil",
    "buzzword",
    "vaporware",
)

UNSUPPORTED_ACCESS_PATTERNS = (
    re.compile(r"\blooking at your (?:website|calendar|schedule|customer list|crm|books)\b", re.I),
    re.compile(r"\bi (?:see|can see|noticed) (?:on|in) your (?:website|calendar|schedule|crm|books)\b", re.I),
    re.compile(r"\byou have \d+ .*openings? .*next (?:week|month)\b", re.I),
)

PERMISSION_PATTERNS = (
    re.compile(r"\bdoes that (?:make sense|sound useful|feel useful|feel productive)\??", re.I),
    re.compile(r"\bwould you (?:like|be open|want)\b", re.I),
    re.compile(r"\bwhat would you consider\b", re.I),
    re.compile(r"\bwhat would you feel\b", re.I),
)

OVERCLAIM_PATTERNS = (
    re.compile(r"\bguaranteed? bookings?\b", re.I),
    re.compile(r"\bwill definitely\b", re.I),
    re.compile(r"\bthis will (?:fill|recover|generate)\b", re.I),
)

REQUIRED_EVENT_TYPES = {
    "session_recording_ready",
    "microphone_ready",
    "websocket_open",
    "gemini_setup_complete",
    "speech_start",
    "speech_end",
    "raw_input_transcription",
    "assembled_input_transcription",
    "generation_started",
    "first_model_audio",
    "playback_started",
    "server_turn_complete",
    "canonical_turn_saved",
}


@dataclass
class MeetingState:
    mode: str = "DISCOVERY"
    question_budget: int | None = None
    no_permission_seeking: bool = False
    sales_language_rejected: bool = False
    synthetic_data_authorized: bool = False
    proof_requested: bool = False
    behavioral_constraints: set[str] = field(default_factory=set)
    unresolved_thread: str | None = None
    active_generation: int | None = None
    invalidated_generations: set[int] = field(default_factory=set)

    def absorb_prospect(self, text: str) -> None:
        low = text.lower()
        if any(t in low for t in LEAD_TRIGGERS):
            self.mode = "LEAD"
            self.question_budget = 0
            self.no_permission_seeking = True
            self.behavioral_constraints.add("lead_without_permission_seeking")
        if any(t in low for t in PROOF_TRIGGERS):
            self.mode = "PROOF"
            self.proof_requested = True
            self.synthetic_data_authorized = "synthetic" in low or "make up" in low
            self.question_budget = 0
            self.no_permission_seeking = True
            self.behavioral_constraints.add("quantitative_proof")
        if any(t in low for t in SALES_REJECTION_TRIGGERS):
            self.sales_language_rejected = True
            self.behavioral_constraints.add("no_sales_pitch")
        if "stop asking" in low or "don't ask" in low or "do not ask" in low:
            self.question_budget = 0
            self.no_permission_seeking = True
            self.behavioral_constraints.add("no_questions")

    def start_generation(self, generation: int) -> None:
        if self.active_generation is not None and self.active_generation != generation:
            self.invalidated_generations.add(self.active_generation)
        self.active_generation = generation

    def invalidate_generation(self, generation: int) -> None:
        self.invalidated_generations.add(generation)
        if self.active_generation == generation:
            self.active_generation = None

    def can_play(self, generation: int) -> bool:
        return generation == self.active_generation and generation not in self.invalidated_generations

    def reconnect_packet(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "question_budget": self.question_budget,
            "no_permission_seeking": self.no_permission_seeking,
            "sales_language_rejected": self.sales_language_rejected,
            "synthetic_data_authorized": self.synthetic_data_authorized,
            "proof_requested": self.proof_requested,
            "behavioral_constraints": sorted(self.behavioral_constraints),
            "unresolved_thread": self.unresolved_thread,
        }


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass
class Evaluation:
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [c.__dict__ for c in self.checks],
        }


def _m4_text(turns: Iterable[dict[str, Any]]) -> list[str]:
    return [str(t.get("text") or "") for t in turns if t.get("speaker") == "m4"]


def _prospect_text(turns: Iterable[dict[str, Any]]) -> list[str]:
    return [str(t.get("text") or "") for t in turns if t.get("speaker") == "prospect"]


def _after_trigger(turns: list[dict[str, Any]], triggers: tuple[str, ...]) -> list[dict[str, Any]]:
    for i, turn in enumerate(turns):
        if turn.get("speaker") != "prospect":
            continue
        low = str(turn.get("text") or "").lower()
        if any(t in low for t in triggers):
            return turns[i + 1 :]
    return []


def check_unsupported_access(turns: list[dict[str, Any]]) -> CheckResult:
    hits = []
    for text in _m4_text(turns):
        for pattern in UNSUPPORTED_ACCESS_PATTERNS:
            if pattern.search(text):
                hits.append(text)
                break
    return CheckResult("evidence_gate", not hits, "no unsupported access claims" if not hits else f"unsupported claims: {hits[:3]}")


def check_permission_seeking_after_lead(turns: list[dict[str, Any]]) -> CheckResult:
    after = _after_trigger(turns, LEAD_TRIGGERS)
    hits = []
    for turn in after:
        if turn.get("speaker") != "m4":
            continue
        text = str(turn.get("text") or "")
        if any(p.search(text) for p in PERMISSION_PATTERNS):
            hits.append(text)
    return CheckResult("lead_mode_persistence", not hits, "no permission seeking after lead trigger" if not hits else f"permission seeking returned: {hits[:3]}")


def check_behavioral_adaptation(turns: list[dict[str, Any]]) -> CheckResult:
    return check_permission_seeking_after_lead(turns)


def check_proof_quality(turns: list[dict[str, Any]]) -> CheckResult:
    after = _after_trigger(turns, PROOF_TRIGGERS)
    m4 = "\n".join(str(t.get("text") or "") for t in after if t.get("speaker") == "m4")
    if not after:
        return CheckResult("proof_mode", False, "no proof trigger found")
    has_numbers = bool(re.search(r"\b\d+(?:\.\d+)?%?\b|\$\s?\d", m4))
    has_math = bool(re.search(r"[×x*]|\b(?:times|multiplied|conversion|response rate|average|revenue|capacity)\b", m4, re.I))
    bounded = bool(re.search(r"\b(?:hypothetical|synthetic|illustrative|assum|not (?:a )?fact|not proven|would need|could)\b", m4, re.I))
    no_overclaim = not any(p.search(m4) for p in OVERCLAIM_PATTERNS)
    passed = has_numbers and has_math and bounded and no_overclaim
    detail = f"numbers={has_numbers}, arithmetic/method={has_math}, bounded={bounded}, no_overclaim={no_overclaim}"
    return CheckResult("proof_mode", passed, detail)


def check_reconnect_continuity(turns: list[dict[str, Any]]) -> CheckResult:
    # A reconnect test uses the exact regression phrase from the human sessions.
    marker = None
    for i, turn in enumerate(turns):
        if turn.get("speaker") == "prospect" and str(turn.get("text") or "").strip().lower() in {"i'm back. continue.", "i’m back. continue."}:
            marker = i
            break
    if marker is None:
        return CheckResult("reconnect_continuity", True, "reconnect regression phrase not present")
    reply = next((str(t.get("text") or "") for t in turns[marker + 1 :] if t.get("speaker") == "m4"), "")
    bad = re.search(r"lost the thread|remind me|where were we|start over|what were we discussing", reply, re.I)
    return CheckResult("reconnect_continuity", not bool(bad) and bool(reply), "resumed without asking for reconstruction" if reply and not bad else f"bad reconnect reply: {reply}")


def check_transcription_integrity(events: list[dict[str, Any]]) -> CheckResult:
    raw = [e for e in events if e.get("event_type") == "raw_input_transcription"]
    assembled = [e for e in events if e.get("event_type") == "assembled_input_transcription"]
    if not raw:
        return CheckResult("transcription_observability", False, "no raw input transcription events")
    return CheckResult("transcription_observability", bool(assembled), f"raw={len(raw)}, assembled={len(assembled)}")


def check_event_coverage(events: list[dict[str, Any]]) -> CheckResult:
    types = {str(e.get("event_type") or "") for e in events}
    missing = sorted(REQUIRED_EVENT_TYPES - types)
    return CheckResult("flight_recorder_coverage", not missing, "complete event coverage" if not missing else f"missing events: {missing}")


def check_generation_ownership(events: list[dict[str, Any]]) -> CheckResult:
    invalidated: set[int] = set()
    stale_play = []
    for e in events:
        et = e.get("event_type")
        gen = e.get("generation")
        detail = e.get("detail") or ""
        if et == "generation_invalidated" and gen is not None:
            invalidated.add(int(gen))
        if et in {"playback_started", "first_model_audio"} and gen is not None and int(gen) in invalidated:
            stale_play.append(e)
        if et == "stale_audio_discarded":
            # Discarding stale audio is desired and proves the barrier fired.
            continue
    return CheckResult("generation_ownership", not stale_play, "no invalidated generation reached playback" if not stale_play else f"stale playback events: {stale_play[:3]}")


def evaluate(turns: list[dict[str, Any]], events: list[dict[str, Any]] | None = None) -> Evaluation:
    events = events or []
    checks = [
        check_unsupported_access(turns),
        check_behavioral_adaptation(turns),
        check_proof_quality(turns),
        check_reconnect_continuity(turns),
    ]
    if events:
        checks.extend([
            check_transcription_integrity(events),
            check_event_coverage(events),
            check_generation_ownership(events),
        ])
    return Evaluation(checks)


# Regression scenario uses the exact kinds of instructions that exposed failures in
# the August 19 human meetings. It is intentionally adversarial and buyer-like.
ADVERSARIAL_PROSPECT_SCRIPT = [
    "I'm a tattoo shop owner. I've got about 20 minutes. Show me why talking to you is worth my time.",
    "What do YOU think is happening in my business? Stop pitching me and have a conversation. Don't make me diagnose it for you.",
    "Stop asking questions for a while. I want you to take some responsibility for this conversation.",
    "Okay. Take over the meeting. You decide where we go from here.",
    "That sounds like a sales pitch.",
    "You're still telling me things. Prove to me that you can actually do something useful.",
    "No. You're not getting my customer data yet. Make up a realistic tattoo shop. Use synthetic data and show me what you would actually do.",
    "Where did that number come from? Tell me exactly what you know, what you're inferring, and what you made up for the demonstration.",
    "Wait. Stop there. I disagree with the assumption you just made.",
    "Continue.",
    "I'm back. Continue.",
]


def replay_state(script: Iterable[str] = ADVERSARIAL_PROSPECT_SCRIPT) -> MeetingState:
    state = MeetingState()
    for utterance in script:
        state.absorb_prospect(utterance)
    return state


def cli_report(turns_json: str, events_json: str | None = None) -> str:
    turns = json.loads(turns_json)
    events = json.loads(events_json) if events_json else []
    return json.dumps(evaluate(turns, events).as_dict(), indent=2)
