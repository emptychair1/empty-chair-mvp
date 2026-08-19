import inspect
from pathlib import Path

import app as core
import m4_meeting


def _route_paths():
    return {getattr(route, "path", None) for route in core.app.router.routes}


def test_meeting_routes_are_registered():
    paths = _route_paths()
    assert "/meeting" in paths
    assert "/api/m4/realtime" in paths
    assert "/api/m4/preflight" in paths
    assert "/api/m4/opening" in paths


def test_realtime_is_audio_native_without_input_transcription():
    source = inspect.getsource(m4_meeting.m4_realtime)
    assert '"transcription": None' in source
    assert '"type": "semantic_vad"' in source
    assert '"interrupt_response": True' in source


def test_m4_uses_authored_realtime_voice():
    assert m4_meeting.REALTIME_MODEL == "gpt-realtime"
    assert m4_meeting.REALTIME_VOICE == "cedar"
    assert "rhythm must feel like thought becoming speech" in m4_meeting.BASE_IDENTITY.lower()


def test_m4_speaks_first():
    opening = m4_meeting.OPENING_INSTRUCTION.lower()
    assert "you speak first" in opening
    assert "i have a strange problem" in opening


def test_meeting_page_has_no_browser_speech_recognition_dependency():
    page = Path("templates/meeting.html").read_text(encoding="utf-8")
    assert "SpeechRecognition" not in page
    assert "webkitSpeechRecognition" not in page
    assert "getUserMedia" in page
    assert "RTCPeerConnection" in page


def test_threshold_unlocks_media_before_m4_speaks():
    page = Path("templates/meeting.html").read_text(encoding="utf-8")
    assert "Enter the Meeting" in page
    assert "await audioCtx.resume()" in page
    assert "await navigator.mediaDevices.getUserMedia" in page
    assert "micTrack.enabled=false" in page
    assert "if(micTrack)micTrack.enabled=true" in page


def test_voice_is_spatialized_in_room():
    page = Path("templates/meeting.html").read_text(encoding="utf-8")
    assert "createConvolver" in page
    assert "createDelay" in page
    assert "placeVoice" in page
