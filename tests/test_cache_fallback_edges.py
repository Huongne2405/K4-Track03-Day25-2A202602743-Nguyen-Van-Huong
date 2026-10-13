"""Check cache invalidation and expiration while a provider call is in flight."""

import pytest

from gameday_lab.cache import CachingClient, SemanticCache
from gameday_lab.sim.contracts import (
    Action,
    Answer,
    Attempt,
    BaseClient,
    CallContext,
    GiveUp,
    ProviderError,
    Request,
    Send,
    Serve,
)


def request(version: str = "v1") -> Request:
    return Request("refund policy", "u1", False, version, (1.0, 0.0))


class FailingInner(BaseClient):
    def start(self, call: CallContext, now: float) -> Action:
        return Send("primary", timeout_s=1.0)

    def on_error(self, attempt: Attempt, err: ProviderError, now: float) -> Action:
        return GiveUp("no_provider_available")


@pytest.mark.parametrize("change", ["none", "invalidate", "expire"])
def test_fallback_rechecks_entry_after_provider_attempt(change: str) -> None:
    cache = SemanticCache(ttl_s=1.0, max_stale_s=2.0)
    answer = Answer(1, "v1", ("policy/refund",), 0.0)
    cache.store(request(), answer, 0.0)
    client = CachingClient(FailingInner(), cache)
    call = CallContext(1, 1, "chat", 2.0, 30.0, request=request())
    send = client.start(call, 2.0)
    assert isinstance(send, Send)
    now = 2.1
    if change == "invalidate":
        client.on_content_update("policy/refund", now)
    elif change == "expire":
        now = 3.1
    action = client.on_error(
        Attempt(call, send.provider, 1, 2.0, send.tag),
        ProviderError("primary", 503, "service_unavailable"), now,
    )
    if change == "none":
        assert isinstance(action, Serve) and action.answer == answer and action.stale
    else:
        assert isinstance(action, GiveUp)


def test_stale_access_does_not_extend_entry_lifetime() -> None:
    cache = SemanticCache(ttl_s=1.0, max_stale_s=2.0)
    cache.store(request(), Answer(1, "v1", ("policy/refund",), 0.0), 0.0)
    assert cache.lookup(request(), 2.0) is not None
    assert cache.lookup(request(), 3.0) is not None
    assert cache.lookup(request(), 3.1) is None
    assert cache.entries == []


def test_source_update_invalidates_all_prompt_scopes() -> None:
    cache = SemanticCache()
    for idx, version in enumerate(("v1", "v2"), start=1):
        cache.store(request(version), Answer(idx, version, ("policy/refund", "policy/orders"), 0.0), 0.0)
    assert cache.invalidate("policy/orders", 1.0) == 2
    assert cache.entries == []


def test_answer_with_mismatched_prompt_version_is_not_stored() -> None:
    cache = SemanticCache()
    cache.store(request("v1"), Answer(1, "v2", ("policy/refund",), 0.0), 0.0)
    assert cache.entries == []
