import m4_behavior_state as behavior


def test_take_over_locks_lead_mode_and_question_budget():
    state = behavior.default_state('s1')
    behavior.absorb_text(state, 'Stop asking questions. Take over this meeting.')
    assert state['mode'] == 'LEAD'
    assert state['question_budget'] == 0
    assert state['no_permission_seeking'] is True
    directive = behavior.runtime_directive(state)
    assert 'QUESTION BUDGET IS ZERO' in directive
    assert 'Do not ask permission' in directive


def test_prove_it_locks_quantitative_proof_mode():
    state = behavior.default_state('s2')
    behavior.absorb_text(state, 'Use synthetic data and prove it to me with an example.')
    assert state['mode'] == 'PROOF'
    assert state['proof_requested'] is True
    assert state['synthetic_data_authorized'] is True
    directive = behavior.runtime_directive(state)
    assert 'numbers, arithmetic' in directive
    assert 'Label every invented fact synthetic' in directive


def test_sales_rejection_persists_when_later_turn_changes_topic():
    state = behavior.default_state('s3')
    behavior.absorb_text(state, 'That sounds like a sales pitch. Stop pitching me.')
    behavior.absorb_text(state, 'Continue.')
    assert state['no_sales_pitch'] is True
    assert 'no_sales_pitch' in state['constraints']
    assert 'Sales language is rejected' in behavior.runtime_directive(state)


def test_im_back_continue_sets_exact_thread_constraint_without_erasing_prior_state():
    state = behavior.default_state('s4')
    behavior.absorb_text(state, "Don't ask me questions. You take over.")
    behavior.absorb_text(state, "I'm back. Continue.")
    assert state['continue_exact_thread'] is True
    assert state['question_budget'] == 0
    assert state['no_permission_seeking'] is True
    directive = behavior.runtime_directive(state)
    assert 'Continue the exact unresolved intellectual thread' in directive


def test_long_adversarial_conversation_preserves_stacked_constraints():
    state = behavior.default_state('s5')

    turns = [
        "Stop asking questions. Take over this meeting.",
        "That sounds like a sales pitch. Stop pitching me.",
        "Use synthetic data and prove it to me with an example.",
        "Fine. Keep going.",
        "I disagree with that assumption.",
        "Continue.",
        "I'm back. Continue.",
    ]

    for turn in turns:
        behavior.absorb_text(state, turn)

    assert state['mode'] == 'PROOF'
    assert state['question_budget'] == 0
    assert state['no_permission_seeking'] is True
    assert state['no_sales_pitch'] is True
    assert state['proof_requested'] is True
    assert state['synthetic_data_authorized'] is True
    assert state['continue_exact_thread'] is True

    constraints = set(state['constraints'])
    assert 'lead_without_permission_seeking' in constraints
    assert 'no_questions' in constraints
    assert 'no_sales_pitch' in constraints
    assert 'quantitative_proof' in constraints
    assert 'synthetic_data_authorized' in constraints
    assert 'continue_exact_thread' in constraints

    directive = behavior.runtime_directive(state)
    assert 'QUESTION BUDGET IS ZERO' in directive
    assert 'Do not ask permission' in directive
    assert 'Sales language is rejected' in directive
    assert 'Proof is requested' in directive
    assert 'Label every invented fact synthetic' in directive
    assert 'Continue the exact unresolved intellectual thread' in directive


def test_long_adversarial_conversation_does_not_restore_discovery_defaults():
    state = behavior.default_state('s6')

    behavior.absorb_text(state, "Don't ask me questions. Take over.")
    behavior.absorb_text(state, 'Stop pitching me.')
    behavior.absorb_text(state, 'Use synthetic data and prove it.')

    neutral_followups = [
        'Okay.',
        'Go on.',
        'That part is interesting.',
        'I disagree.',
        'Explain that.',
        'Continue.',
    ]

    for turn in neutral_followups:
        behavior.absorb_text(state, turn)
        assert state['mode'] == 'PROOF'
        assert state['question_budget'] == 0
        assert state['no_permission_seeking'] is True
        assert state['no_sales_pitch'] is True
        assert state['proof_requested'] is True
        assert state['synthetic_data_authorized'] is True


def test_transport_patch_contains_completed_turn_behavior_injection():
    import m4_gemini_transport_patch as patch
    assert '/api/m4/prospect-behavior' in patch._BEHAVIOR_FUNCTION_REPLACEMENT
    assert 'turnComplete:false' in patch._BEHAVIOR_FUNCTION_REPLACEMENT
    assert 'await updateBehavior(userText)' in patch._SAVE_PROSPECT_REPLACEMENT
