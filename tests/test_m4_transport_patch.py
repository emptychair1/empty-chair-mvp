import m4_gemini_transport_patch as patch


def test_transport_patch_targets_expected_client_code():
    assert "invalidated_generation" in patch._NEW_RESET
    assert "new_generation" not in patch._NEW_RESET
    assert "resetAudio('gemini_interrupted_ack')" in patch._OLD_ACK
    assert "resetAudio('gemini_interrupted_ack')" not in patch._NEW_ACK


def test_transport_patch_preserves_single_m4_smooth_route():
    import app as core
    matches = [
        route for route in core.app.router.routes
        if getattr(route, 'path', None) == '/m4-smooth'
        and 'GET' in (getattr(route, 'methods', set()) or set())
    ]
    assert len(matches) == 1
