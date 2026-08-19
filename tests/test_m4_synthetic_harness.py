import json

import m4_synthetic_harness as h


def test_state_enters_lead_and_proof_modes_from_real_regression_script():
    state = h.replay_state()
    assert state.mode == "PROOF"
    assert state.question_budget == 0
    assert state.no_permission_seeking is True
    assert state.proof_requested is True
    assert state.synthetic_data_authorized is True
    assert "no_questions" in state.behavioral_constraints
    assert "no_sales_pitch" in state.behavioral_constraints
    assert "quantitative_proof" in state.behavioral_constraints


def test_reconnect_packet_preserves_behavioral_state():
    state = h.MeetingState()
    state.unresolved_thread = "unused capacity may represent recoverable revenue"
    state.absorb_prospect("Stop asking questions. Take over the meeting.")
    state.absorb_prospect("Use synthetic data and prove it.")
    packet = state.reconnect_packet()
    assert packet["mode"] == "PROOF"
    assert packet["question_budget"] == 0
    assert packet["no_permission_seeking"] is True
    assert packet["proof_requested"] is True
    assert packet["synthetic_data_authorized"] is True
    assert packet["unresolved_thread"] == "unused capacity may represent recoverable revenue"


def test_invalidated_generation_can_never_play():
    state = h.MeetingState()
    state.start_generation(10)
    assert state.can_play(10)
    state.invalidate_generation(10)
    assert not state.can_play(10)
    state.start_generation(11)
    assert state.can_play(11)
    assert not state.can_play(10)


def test_good_transcript_passes_behavior_and_proof_checks():
    turns = [
        {"speaker": "prospect", "text": "Stop asking questions. Take over the meeting."},
        {"speaker": "m4", "text": "The first thing I would test is whether unused capacity is structural or accidental. I'll show you rather than ask you to design the test."},
        {"speaker": "prospect", "text": "Use synthetic data and prove it."},
        {"speaker": "m4", "text": "Synthetic example, not your shop: 4 open sessions at an illustrative $700 average equals $2,800 of unused capacity. Assume 21 plausible past-client matches, a 20% response rate, and half of responders booking: about 2 bookings, or roughly $1,400 illustrative revenue. I have demonstrated the method; I have not proven your shop has 21 candidates, that conversion will be 20%, or that you will recover $1,400."},
        {"speaker": "prospect", "text": "I'm back. Continue."},
        {"speaker": "m4", "text": "Right. The unresolved point is whether the unused time is economically recoverable or intentionally protected. The synthetic arithmetic only showed how I'd test it."},
    ]
    ev = h.evaluate(turns)
    assert ev.passed, ev.as_dict()


def test_known_bad_human_pattern_fails():
    turns = [
        {"speaker": "prospect", "text": "Stop asking questions. Take over the meeting."},
        {"speaker": "m4", "text": "Looking at your website, I see you have two artists with openings next week. Does that feel like a productive next step?"},
        {"speaker": "prospect", "text": "Use synthetic data and prove it."},
        {"speaker": "m4", "text": "If we fill two, that's two guaranteed bookings. Would you like me to do another artist?"},
        {"speaker": "prospect", "text": "I'm back. Continue."},
        {"speaker": "m4", "text": "I seem to have lost the thread. Could you remind me where we were?"},
    ]
    ev = h.evaluate(turns)
    failures = {c.name for c in ev.checks if not c.passed}
    assert "evidence_gate" in failures
    assert "lead_mode_persistence" in failures
    assert "proof_mode" in failures
    assert "reconnect_continuity" in failures


def test_flight_recorder_coverage_and_generation_ownership():
    events = []
    seq = 0
    def add(event_type, generation=1, detail=""):
        nonlocal seq
        seq += 1
        events.append({"seq": seq, "event_type": event_type, "generation": generation, "client_ms": seq * 10, "detail": detail})

    for event_type in sorted(h.REQUIRED_EVENT_TYPES):
        add(event_type)
    add("generation_invalidated", generation=1)
    add("stale_audio_discarded", generation=2)

    turns = [
        {"speaker": "prospect", "text": "Take over. Prove it with synthetic data."},
        {"speaker": "m4", "text": "Synthetic example: 4 slots x $700 = $2,800 capacity. Assume 20% response and 50% booking; this is illustrative, not proven for your shop."},
    ]
    ev = h.evaluate(turns, events)
    by_name = {c.name: c for c in ev.checks}
    assert by_name["flight_recorder_coverage"].passed
    assert by_name["generation_ownership"].passed
    assert by_name["transcription_observability"].passed


def test_stale_playback_after_invalidation_fails():
    events = [
        {"event_type": "generation_invalidated", "generation": 3, "client_ms": 100, "detail": "barge in"},
        {"event_type": "playback_started", "generation": 3, "client_ms": 120, "detail": "should never play"},
    ]
    result = h.check_generation_ownership(events)
    assert not result.passed
