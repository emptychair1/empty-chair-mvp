import meeting_v2


def test_meeting_v2_lead_mode_persists_zero_question_budget():
    state = meeting_v2._default_state()
    meeting_v2._absorb(state, "Stop asking questions. Take over this meeting.")
    assert state["mode"] == "LEAD"
    assert state["question_budget"] == 0
    assert state["no_permission_seeking"] is True
    directive = meeting_v2._directive(state)
    assert "QUESTION BUDGET IS ZERO" in directive
    assert "Do not ask permission" in directive


def test_meeting_v2_proof_and_synthetic_constraints_stack():
    state = meeting_v2._default_state()
    meeting_v2._absorb(state, "Stop pitching me.")
    meeting_v2._absorb(state, "Use synthetic data and prove it.")
    assert state["mode"] == "PROOF"
    assert state["no_sales_pitch"] is True
    assert state["proof_requested"] is True
    assert state["synthetic_data_authorized"] is True
    directive = meeting_v2._directive(state)
    assert "Sales language is rejected" in directive
    assert "numbers, arithmetic" in directive
    assert "Label every invented fact synthetic" in directive


def test_meeting_v2_continue_does_not_erase_prior_constraints():
    state = meeting_v2._default_state()
    meeting_v2._absorb(state, "Don't ask me questions. You take over.")
    meeting_v2._absorb(state, "Stop pitching me.")
    meeting_v2._absorb(state, "I'm back. Continue.")
    assert state["continue_exact_thread"] is True
    assert state["question_budget"] == 0
    assert state["no_sales_pitch"] is True
    assert "Continue the exact unresolved thread" in meeting_v2._directive(state)


def test_meeting_v2_html_contains_identity_and_no_app_chrome():
    html = meeting_v2._meeting_html()
    assert "The Meeting" in html
    assert "presence" in html
    assert "feTurbulence" in html
    assert "api/meeting-v2/turn" in html
    assert "sidebar" not in html
    assert "Shop Intelligence" not in html


def test_meeting_v2_voice_is_elevenlabs_configurable():
    assert meeting_v2.ELEVENLABS_MODEL_ID
    assert meeting_v2.ELEVENLABS_VOICE_ID
