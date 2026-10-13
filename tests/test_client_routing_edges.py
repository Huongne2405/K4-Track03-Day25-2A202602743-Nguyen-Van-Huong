"""Cooldown and deadline boundaries not covered by the starter client tests."""

from gameday_lab.client import ResilientClient
from gameday_lab.sim.contracts import Attempt, CallContext, GiveUp, ProviderError, ProviderInfo, Send


def make_client(**settings: object) -> ResilientClient:
    providers = {"primary": ProviderInfo("primary", "A", "us", True, 1.0)}
    return ResilientClient(providers, ["primary"], {"quota_cooldown_s": 2.0, **settings}, seed=7)


def test_short_quota_cooldown_is_not_treated_as_a_rate_limit_wait() -> None:
    client = make_client()
    call = CallContext(1, 1, "tool", 0.0, 30.0)
    send = client.start(call, 0.0)
    assert isinstance(send, Send)
    action = client.on_error(
        Attempt(call, send.provider, 1, 0.0, send.tag),
        ProviderError("primary", 429, "insufficient_quota"), 1.0,
    )
    assert isinstance(action, GiveUp)


def test_rate_limit_wait_honours_cooldown_and_attempt_limit() -> None:
    client = make_client(max_attempts_per_provider=2)
    call = CallContext(1, 1, "tool", 0.0, 30.0)
    send = client.start(call, 0.0)
    assert isinstance(send, Send)
    err = ProviderError("primary", 429, "rate_limit_exceeded", retry_after=2.0)
    retry = client.on_error(Attempt(call, send.provider, 1, 0.0, send.tag), err, 1.0)
    assert isinstance(retry, Send) and retry.delay_s >= 2.0
    action = client.on_error(Attempt(call, retry.provider, 2, 3.0, retry.tag), err, 3.1)
    assert isinstance(action, GiveUp)


def test_rate_limit_wait_cannot_bypass_empty_retry_budget() -> None:
    client = make_client(retry_budget_ratio=0.0, retry_budget_min_per_s=0.0, retry_budget_max_tokens=0.0)
    call = CallContext(1, 1, "tool", 0.0, 30.0)
    send = client.start(call, 0.0)
    assert isinstance(send, Send)
    action = client.on_error(
        Attempt(call, send.provider, 1, 0.0, send.tag),
        ProviderError("primary", 429, "rate_limit_exceeded", retry_after=2.0), 1.0,
    )
    assert isinstance(action, GiveUp)


def test_transient_retry_after_that_cannot_fit_deadline_does_not_spend_budget() -> None:
    client = make_client()
    call = CallContext(1, 1, "tool", 0.0, 3.0)
    send = client.start(call, 0.0)
    assert isinstance(send, Send)
    before = client.budget.tokens
    action = client.on_error(
        Attempt(call, send.provider, 1, 0.0, send.tag),
        ProviderError("primary", 503, "service_unavailable", retry_after=2.0), 1.0,
    )
    assert isinstance(action, GiveUp)
    assert client.budget.tokens == before


def test_transient_retry_after_is_honoured_when_it_fits() -> None:
    client = make_client()
    call = CallContext(1, 1, "tool", 0.0, 30.0)
    send = client.start(call, 0.0)
    assert isinstance(send, Send)
    action = client.on_error(
        Attempt(call, send.provider, 1, 0.0, send.tag),
        ProviderError("primary", 503, "service_unavailable", retry_after=2.0), 1.0,
    )
    assert isinstance(action, Send) and action.delay_s >= 2.0


def test_concurrent_rate_limit_responses_cannot_shorten_shared_cooldown() -> None:
    client = make_client()
    calls = [CallContext(i, i, "tool", 0.0, 30.0) for i in (1, 2)]
    sends = [client.start(call, 0.0) for call in calls]
    for i, (call, send, wait) in enumerate(zip(calls, sends, (10.0, 1.0)), start=1):
        assert isinstance(send, Send)
        client.on_error(
            Attempt(call, send.provider, 1, 0.0, send.tag),
            ProviderError("primary", 429, "rate_limit_exceeded", retry_after=wait), float(i),
        )
    assert client.cooldown_until["primary"] == 11.0
