"""Verify side effects around checkpoint writes and exhausted retries."""

from typing import Any

import pytest

from gameday_lab.workflows.executor import WorkflowExecutor, checkpoint_key, idempotency_key
from gameday_lab.workflows.runner import RefundRequest
from gameday_lab.workflows.services import DurableStore, FaultProfile, ServiceError, Services, WorkerCrash

REQ = RefundRequest("session-1", "order-1", 4900, "user@example.com")
NO_FAULTS = FaultProfile(0.0, 0.0, 0.0)


@pytest.mark.parametrize("write_before_crash", [False, True])
def test_crash_during_refund_checkpoint_write_resumes_without_repeating_effects(write_before_crash: bool) -> None:
    class CrashingStore(DurableStore):
        crashed = False

        def put(self, key: str, value: Any) -> None:
            if key == checkpoint_key(REQ, "issue_refund") and not self.crashed:
                self.crashed = True
                if write_before_crash:
                    super().put(key, value)
                raise WorkerCrash("checkpoint write interrupted")
            super().put(key, value)

    services, store = Services.build(1, NO_FAULTS), CrashingStore()
    with pytest.raises(WorkerCrash):
        WorkflowExecutor(services, store).run(REQ)
    assert len(services.payments.ledger) == 1
    assert services.llm.executions == 1
    result = WorkflowExecutor(services, store).run(REQ)
    assert result["status"] == "done"
    assert len(services.payments.ledger) == 1
    assert len(services.email.outbox) == 1
    assert services.llm.executions == 2


def test_lost_email_response_does_not_send_twice() -> None:
    services, store = Services.build(1, NO_FAULTS), DurableStore()
    services.email.faults = FaultProfile(0.0, 1.0, 0.0)
    assert WorkflowExecutor(services, store).run(REQ)["status"] == "done"
    assert services.email.requests == 2
    assert services.email.executions == 1
    assert len(services.email.outbox) == 1


def test_exhausted_payment_retries_leave_no_success_checkpoint() -> None:
    services, store = Services.build(1, NO_FAULTS), DurableStore()
    services.payments.faults = FaultProfile(1.0, 0.0, 0.0)
    with pytest.raises(ServiceError):
        WorkflowExecutor(services, store, max_attempts=3).run(REQ)
    assert services.payments.requests == 3
    assert services.payments.executions == 0
    assert services.email.requests == 0
    assert set(store.keys()) == {
        checkpoint_key(REQ, "classify_request"), checkpoint_key(REQ, "lookup_order"),
    }
    services.payments.faults = NO_FAULTS
    assert WorkflowExecutor(services, store).run(REQ)["status"] == "done"
    assert services.llm.executions == 2
    assert services.payments.executions == 1


def test_keys_do_not_collide_when_session_or_step_contains_a_separator() -> None:
    req_a = RefundRequest("session:part", "order-1", 4900, "user@example.com")
    req_b = RefundRequest("session", "order-1", 4900, "user@example.com")
    assert idempotency_key(req_a, "refund") != idempotency_key(req_b, "part:refund")
    assert checkpoint_key(req_a, "refund") != checkpoint_key(req_b, "part:refund")
    assert idempotency_key(REQ, "issue_refund") != checkpoint_key(REQ, "issue_refund")
