from pathlib import Path


def source():
    return Path('m4_gemini_transport_patch.py').read_text()


def test_live_model_uses_minimal_thinking_for_latency():
    text = source()
    assert "thinkingConfig:{thinkingLevel:'minimal'}" in text


def test_presence_controller_has_bounded_two_stage_visual_cues():
    text = source()
    assert 'PRESENCE_SOFT_MS=900' in text
    assert 'PRESENCE_HARD_MS=2400' in text
    assert "set('considering')" in text
    assert "set('working through that')" in text
    assert "evt('presence_soft'" in text
    assert "evt('presence_hard'" in text


def test_presence_controller_never_injects_spoken_filler():
    text = source()
    # Presence is UI/telemetry only. It must not send synthetic speech/client turns.
    segment = text[text.index('_FINALIZE_REPLACEMENT'):text.index('_ENQUEUE_TARGET')]
    assert "send({clientContent" not in segment
    assert "I'm still here" not in segment
    assert "I need a moment" not in segment


def test_first_audio_and_reset_cancel_presence_state():
    text = source()
    assert "firstModelAudioAt=performance.now();clearPresenceCue()" in text
    assert "generation++;clearPresenceCue();" in text
    assert "clearPresenceCue();evt('playback_drained'" in text
