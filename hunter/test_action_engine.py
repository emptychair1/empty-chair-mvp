from datetime import datetime, timedelta, timezone

import httpx
import pytest

from action_engine import (
    ACTION_TYPE,
    SCHEMA,
    action_payload,
    eligibility,
    run_actions,
    send_webhook,
    valid_webhook_url,
)

NOW = datetime(2026, 9, 6, 14, 0, tzinfo=timezone.utc)


def target(**overrides):
    base = {
        "account_id": "acct-1",
        "username": "needle.person",
        "profile_url": "https://www.instagram.com/needle.person/",
        "score": 95,
        "score_state": "HOT",
        "queue_state": "HOT",
        "eligible": True,
        "priority": 1,
        "action_key": "action-abc",
        "last_action_at": None,
        "signal_ids": ["sig-1"],
        "components": [{"rule": "explicit_cancellation", "points": 35, "evidence": "had a cancellation"}],
        "location": {"city": "Athens", "region": "GA", "country": "US"},
    }
    base.update(overrides)
    return base


def queue(*targets):
    items = list(targets) or [target()]
    return {
        "schema": "empty-chair-hunter-queue-v1",
        "generated_at": NOW.isoformat(),
        "target_count": len(items),
        "eligible_count": len(items),
        "batch_size": 50,
        "next_action_batch": items,
        "targets": items,
    }


def action_history(*results):
    return {"schema": SCHEMA, "results": list(results)}


def test_webhook_requires_safe_https_url():
    assert valid_webhook_url("https://actions.tryemptychair.com/hunter") is True
    assert valid_webhook_url("http://actions.tryemptychair.com/hunter") is False
    assert valid_webhook_url("https://user:pass@example.com/x") is False
    assert valid_webhook_url("") is False


def test_action_payload_preserves_target_evidence_without_secret_config():
    payload = action_payload(target(), now=NOW)
    assert payload["action_type"] == ACTION_TYPE
    assert payload["account_id"] == "acct-1"
    assert payload["action_key"] == "action-abc"
    assert payload["signal_ids"] == ["sig-1"]
    assert payload["components"][0]["rule"] == "explicit_cancellation"
    assert "webhook" not in str(payload).lower()
    assert "token" not in str(payload).lower()


def test_queue_eligibility_is_rechecked_before_execution():
    allowed, reason = eligibility(target(eligible=False), None, now=NOW)
    assert allowed is False
    assert reason == "queue_not_eligible"


def test_cooldown_is_rechecked_before_execution():
    allowed, reason = eligibility(
        target(last_action_at=(NOW - timedelta(hours=2)).isoformat()),
        None,
        now=NOW,
    )
    assert allowed is False
    assert reason == "target_cooldown"


def test_successful_action_history_blocks_same_action_key():
    history = action_history({
        "status": "SUCCEEDED",
        "account_id": "acct-1",
        "action_key": "action-abc",
    })
    allowed, reason = eligibility(target(), history, now=NOW)
    assert allowed is False
    assert reason == "duplicate_successful_action"


def test_preview_never_sends_or_marks_target_actioned():
    def handler(request):
        raise AssertionError("preview must never send")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    actions, updated = run_actions(queue(target()), now=NOW, mode="preview", client=client)
    assert actions["status_counts"] == {"PREVIEW": 1}
    assert updated["targets"][0]["queue_state"] == "HOT"
    assert updated["targets"][0]["eligible"] is True


def test_execute_without_approved_adapter_is_blocked_not_fake_success():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(204)))
    actions, updated = run_actions(queue(target()), now=NOW, mode="execute", client=client)
    assert actions["status_counts"] == {"BLOCKED": 1}
    assert actions["results"][0]["reason"] == "approved_webhook_not_configured"
    assert updated["targets"][0]["queue_state"] == "HOT"


def test_successful_webhook_marks_queue_actioned_and_records_history_fields():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(202)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    actions, updated = run_actions(
        queue(target()),
        now=NOW,
        mode="execute",
        webhook_url="https://actions.tryemptychair.com/hunter",
        webhook_token="secret-not-for-artifacts",
        client=client,
        sleep=lambda _: None,
    )
    assert actions["status_counts"] == {"SUCCEEDED": 1}
    assert actions["results"][0]["attempts"] == 1
    assert actions["results"][0]["http_status"] == 202
    assert updated["targets"][0]["queue_state"] == "ACTIONED"
    assert updated["targets"][0]["eligible"] is False
    assert updated["targets"][0]["last_action_key"] == "action-abc"
    assert updated["targets"][0]["last_action_at"]
    assert len(requests) == 1
    assert requests[0].headers["Idempotency-Key"] == "action-abc"
    assert requests[0].headers["Authorization"] == "Bearer secret-not-for-artifacts"
    assert "secret-not-for-artifacts" not in str(actions)


def test_transient_failures_retry_but_permanent_failure_does_not():
    attempts = []

    def transient(request):
        attempts.append(request)
        return httpx.Response(503 if len(attempts) < 3 else 204)

    client = httpx.Client(transport=httpx.MockTransport(transient))
    success, count, status, reason = send_webhook(
        client,
        "https://actions.tryemptychair.com/hunter",
        action_payload(target(), now=NOW),
        sleep=lambda _: None,
    )
    assert success is True
    assert count == 3
    assert status == 204
    assert reason == "delivered"

    attempts.clear()
    client = httpx.Client(transport=httpx.MockTransport(lambda request: (attempts.append(request), httpx.Response(400))[1]))
    success, count, status, reason = send_webhook(
        client,
        "https://actions.tryemptychair.com/hunter",
        action_payload(target(), now=NOW),
        sleep=lambda _: None,
    )
    assert success is False
    assert count == 1
    assert status == 400
    assert reason == "non_retryable_http"


def test_failed_delivery_does_not_consume_target():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    actions, updated = run_actions(
        queue(target()),
        now=NOW,
        mode="execute",
        webhook_url="https://actions.tryemptychair.com/hunter",
        client=client,
        sleep=lambda _: None,
    )
    assert actions["status_counts"] == {"FAILED": 1}
    assert actions["results"][0]["attempts"] == 3
    assert updated["targets"][0]["queue_state"] == "HOT"
    assert updated["targets"][0]["eligible"] is True


def test_invalid_queue_and_mode_are_rejected():
    with pytest.raises(ValueError):
        run_actions({"schema": "wrong", "next_action_batch": []}, now=NOW)
    with pytest.raises(ValueError):
        run_actions(queue(target()), now=NOW, mode="danger")
