from story_access_probe import classify_boundary


def test_boundary_confirms_authorized_story_surface_only():
    own = {"supported": True, "story_count": 0}
    external = {"supported": True, "stories_exposed": False}
    assert classify_boundary(own, external) == "AUTHORIZED_STORIES_ONLY_UNLESS_META_DOCUMENTS_MORE"


def test_boundary_does_not_claim_story_access_when_own_probe_fails():
    own = {"supported": False, "story_count": 0}
    assert classify_boundary(own, None) == "STORY_ACCESS_NOT_CONFIRMED"
