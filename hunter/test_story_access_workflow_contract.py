from pathlib import Path


def test_story_access_workflow_is_manual_only():
    text = Path("../.github/workflows/hunter-story-access.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "push:" not in text


def test_story_access_workflow_never_runs_outreach():
    text = Path("../.github/workflows/hunter-story-access.yml").read_text(encoding="utf-8")
    assert "action_engine.py" not in text
    assert "HUNTER_ACTION_ENABLED" not in text
