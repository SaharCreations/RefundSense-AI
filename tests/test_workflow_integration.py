"""Real SQL + official PostgresSaver; no in-memory checkpoint substitute."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.types import Command

from refundguard.orders import seed_demo
from refundguard.rules import Customer, RecordUnavailable, Ruleset
from refundguard.rules_evaluation import order_from_dict
from refundguard.workflow import APPROVAL_TTL, Actor, ApprovalWorkflow, workflow_connection

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]
ACTOR = Actor("ORG-DEMO", "reviewer-1")


@pytest.fixture(scope="module")
def session():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    rules = Ruleset(ROOT / "config/demo_ruleset.json", ROOT / "data/policies")
    with workflow_connection(url) as conn:
        service = ApprovalWorkflow(conn, rules)
        service.setup()
        yield conn, rules


@pytest.fixture
def case(session):
    conn, rules = session
    clock = [datetime(2026, 10, 6, 12, tzinfo=UTC)]
    service = ApprovalWorkflow(conn, rules, clock=lambda: clock[0])
    records = json.loads((ROOT / "data/demo_records.json").read_text())
    suffix = str(uuid4())[:8]
    customer = replace(Customer(**records["customers"][0]), customer_id=f"C-{suffix}")
    order = replace(
        order_from_dict(records["orders"][1]),
        order_id=f"O-{suffix}",
        customer_id=customer.customer_id,
    )
    with service.transaction():
        seed_demo(conn, [order], [customer])
    return service, order, clock


def proposal(case):
    service, order, _ = case
    return service.propose(ACTOR, order.order_id, order.customer_id)


def count_ledger(service, wid):
    with service.transaction():
        return service.conn.execute(
            "SELECT count(*) AS n FROM refundguard.demo_refund_ledger WHERE workflow_id=%s",
            (wid,),
        ).fetchone()["n"]


def test_exact_interrupt_and_no_effect_before_approval(case):
    service, _, _ = case
    view = proposal(case)
    assert view["status"] == "pending" and view["expires_at"] is None
    assert view["exact_execution_payload"]["refund"]["refund_amount_minor"] == 8500
    snapshot = service.graph.get_state(service.config(view["workflow_id"]))
    assert snapshot.tasks[0].interrupts[0].value == view
    assert count_ledger(service, view["workflow_id"]) == 0
    assert service._execute(view["workflow_id"])["executed"] is False


def test_approve_restart_retry_and_atomic_audit(case):
    service, order, clock = case
    view = proposal(case)
    # Fresh graph/saver instance loads the durable interrupted checkpoint.
    restarted = ApprovalWorkflow(service.conn, service.ruleset, clock=lambda: clock[0])
    done = restarted.decide(ACTOR, view["workflow_id"], True, view["payload_sha256"])
    assert done["status"] == "executed"
    assert done["result"]["refund_amount_minor"] == 8500
    clock[0] += timedelta(days=1)
    assert restarted.decide(ACTOR, view["workflow_id"], True, view["payload_sha256"]) == done
    assert count_ledger(service, view["workflow_id"]) == 1
    with service.transaction():
        row = service.conn.execute(
            "SELECT refunded_minor, refund_state FROM refundguard.orders "
            "WHERE organization_id=%s AND order_id=%s",
            (ACTOR.organization_id, order.order_id),
        ).fetchone()
        events = service.conn.execute(
            "SELECT event FROM refundguard.audit_events WHERE workflow_id=%s ORDER BY event_id",
            (view["workflow_id"],),
        ).fetchall()
    assert row == {"refunded_minor": 8500, "refund_state": "refunded"}
    assert [e["event"] for e in events] == ["proposed", "approved", "executed"]
    assert (
        service.propose(ACTOR, order.order_id, order.customer_id)["status"] == "assessment_blocked"
    )


def test_reject_is_terminal_and_cannot_be_reversed(case):
    service, _, _ = case
    view = proposal(case)
    rejected = service.decide(ACTOR, view["workflow_id"], False, view["payload_sha256"])
    assert rejected["status"] == "rejected"
    with pytest.raises(ValueError, match="cannot be reversed"):
        service.decide(ACTOR, view["workflow_id"], True, view["payload_sha256"])
    assert count_ledger(service, view["workflow_id"]) == 0


@pytest.mark.parametrize("response", ["yes", 1, None, {"approved": True}])
def test_non_boolean_approval_is_rejected(case, response):
    service, _, _ = case
    view = proposal(case)
    with pytest.raises(ValueError, match="explicit boolean"):
        service.decide(ACTOR, view["workflow_id"], response, view["payload_sha256"])
    assert service.view(ACTOR, view["workflow_id"])["status"] == "pending"


def test_hash_mismatch_cannot_change_payload_or_approve(case):
    service, _, _ = case
    view = proposal(case)
    with pytest.raises(ValueError, match="exact displayed payload"):
        service.decide(ACTOR, view["workflow_id"], True, "0" * 64)
    assert service.view(ACTOR, view["workflow_id"]) == view


def test_cross_organization_workflow_and_checkpoint_access_denied(case):
    service, _, _ = case
    view = proposal(case)
    other = Actor("ORG-OTHER", "reviewer-1")
    for operation in [
        lambda: service.view(other, view["workflow_id"]),
        lambda: service.recover(other, view["workflow_id"]),
        lambda: service.decide(other, view["workflow_id"], True, view["payload_sha256"]),
    ]:
        with pytest.raises(RecordUnavailable):
            operation()
    assert count_ledger(service, view["workflow_id"]) == 0


def test_graph_resume_alone_does_not_grant_permission(case):
    service, _, _ = case
    view = proposal(case)
    with pytest.raises(ValueError, match="durable human decision"):
        service.graph.invoke(
            Command(resume={"workflow_id": view["workflow_id"]}),
            service.config(view["workflow_id"]),
            durability="sync",
        )
    assert count_ledger(service, view["workflow_id"]) == 0
    assert service.view(ACTOR, view["workflow_id"])["status"] == "pending"


def persist_approval_without_resume(service, view, monkeypatch):
    def failed_recover(*args):
        raise RuntimeError("simulated checkpoint/network failure after approval commit")

    with monkeypatch.context() as patch:
        patch.setattr(service, "recover", failed_recover)
        with pytest.raises(RuntimeError, match="simulated checkpoint"):
            service.decide(ACTOR, view["workflow_id"], True, view["payload_sha256"])


@pytest.mark.parametrize("offset", [timedelta(minutes=15), timedelta(minutes=16)])
def test_expiry_at_boundary_and_no_replay_renewal(case, monkeypatch, offset):
    service, _, clock = case
    view = proposal(case)
    persist_approval_without_resume(service, view, monkeypatch)
    approved = service.view(ACTOR, view["workflow_id"])
    assert datetime.fromisoformat(approved["expires_at"]) == clock[0] + APPROVAL_TTL
    clock[0] += offset
    expired = service.decide(ACTOR, view["workflow_id"], True, view["payload_sha256"])
    assert expired["status"] == "expired"
    assert expired["expires_at"] == approved["expires_at"]
    assert count_ledger(service, view["workflow_id"]) == 0


@pytest.mark.parametrize("change", ["order", "customer", "rules"])
def test_live_revalidation_invalidates_changed_approval(case, monkeypatch, change):
    service, order, _ = case
    view = proposal(case)
    persist_approval_without_resume(service, view, monkeypatch)
    with service.transaction():
        if change == "order":
            # Same monetary payload, different revision still needs fresh approval.
            service.conn.execute(
                "UPDATE refundguard.orders SET payment_reference=payment_reference "
                "WHERE organization_id=%s AND order_id=%s",
                (ACTOR.organization_id, order.order_id),
            )
        elif change == "customer":
            service.conn.execute(
                "UPDATE refundguard.customers SET premium_verified=true "
                "WHERE organization_id=%s AND customer_id=%s",
                (ACTOR.organization_id, order.customer_id),
            )
        else:
            monkeypatch.setattr(service.ruleset, "fingerprint", "changed-rules")
    result = service.recover(ACTOR, view["workflow_id"])
    assert result["status"] == "stale"
    assert count_ledger(service, view["workflow_id"]) == 0


def test_live_date_rechecked_when_30_day_deadline_passes(case, monkeypatch):
    service, order, clock = case
    clock[0] = datetime(2026, 10, 6, 23, 59, tzinfo=UTC)
    with service.transaction():
        service.conn.execute(
            "UPDATE refundguard.orders SET delivered_on=%s "
            "WHERE organization_id=%s AND order_id=%s",
            (clock[0].date() - timedelta(days=30), ACTOR.organization_id, order.order_id),
        )
    view = proposal(case)
    persist_approval_without_resume(service, view, monkeypatch)
    clock[0] += timedelta(minutes=2)
    assert service.recover(ACTOR, view["workflow_id"])["status"] == "stale"
    assert count_ledger(service, view["workflow_id"]) == 0


def test_commit_before_graph_failure_replays_receipt(case, monkeypatch):
    service, _, _ = case
    view = proposal(case)
    # Compiled graph already holds the original callable: inject failure in _execute instead.
    original = service._execute

    def fail_after_execution(wid):
        original(wid)
        raise RuntimeError("simulated crash after ledger commit before checkpoint")

    with monkeypatch.context() as patch:
        patch.setattr(service, "_execute", fail_after_execution)
        with pytest.raises(RuntimeError, match="after ledger commit"):
            service.decide(ACTOR, view["workflow_id"], True, view["payload_sha256"])
    recovered = service.recover(ACTOR, view["workflow_id"])
    assert recovered["status"] == "executed"
    assert service._execute(view["workflow_id"]) == recovered["result"]
    assert count_ledger(service, view["workflow_id"]) == 1


def test_failure_before_commit_rolls_back_all_effects(case, monkeypatch):
    service, order, _ = case
    view = proposal(case)
    audit = service._audit

    def fail_execution_audit(row, actor_id, event, detail=None):
        if event == "executed":
            raise RuntimeError("simulated audit write failure")
        return audit(row, actor_id, event, detail)

    with monkeypatch.context() as patch:
        patch.setattr(service, "_audit", fail_execution_audit)
        with pytest.raises(RuntimeError, match="audit write failure"):
            service.decide(ACTOR, view["workflow_id"], True, view["payload_sha256"])
    assert count_ledger(service, view["workflow_id"]) == 0
    with service.transaction():
        row = service.conn.execute(
            "SELECT refunded_minor FROM refundguard.orders "
            "WHERE organization_id=%s AND order_id=%s",
            (ACTOR.organization_id, order.order_id),
        ).fetchone()
    assert row["refunded_minor"] == 0
    assert service.recover(ACTOR, view["workflow_id"])["status"] == "executed"


def test_two_proposals_for_same_order_only_one_executes(case):
    service, _, _ = case
    first, second = proposal(case), proposal(case)
    assert (
        service.decide(ACTOR, first["workflow_id"], True, first["payload_sha256"])["status"]
        == "executed"
    )
    assert (
        service.decide(ACTOR, second["workflow_id"], True, second["payload_sha256"])["status"]
        == "stale"
    )
    assert count_ledger(service, first["workflow_id"]) == 1
    assert count_ledger(service, second["workflow_id"]) == 0


def test_missing_live_order_blocks_execution(case, monkeypatch):
    service, order, _ = case
    view = proposal(case)
    persist_approval_without_resume(service, view, monkeypatch)
    with service.transaction():
        service.conn.execute(
            "DELETE FROM refundguard.orders WHERE organization_id=%s AND order_id=%s",
            (ACTOR.organization_id, order.order_id),
        )
    done = service.recover(ACTOR, view["workflow_id"])
    assert done["status"] == "stale"
    assert done["result"]["reason"] == "live_record_unavailable"
    assert count_ledger(service, view["workflow_id"]) == 0


def test_checkpoint_creation_failure_recovers_pending_proposal(case, monkeypatch):
    service, order, _ = case
    with monkeypatch.context() as patch:

        def fail_checkpoint(*args, **kwargs):
            raise RuntimeError("simulated initial checkpoint failure")

        patch.setattr(service.graph, "invoke", fail_checkpoint)
        with pytest.raises(RuntimeError, match="initial checkpoint"):
            proposal(case)
    with service.transaction():
        row = service.conn.execute(
            "SELECT workflow_id FROM refundguard.workflows "
            "WHERE organization_id=%s AND request->>'order_id'=%s",
            (ACTOR.organization_id, order.order_id),
        ).fetchone()
    wid = str(row["workflow_id"])
    assert service.recover(ACTOR, wid)["status"] == "pending"
    assert service.graph.get_state(service.config(wid)).tasks[0].interrupts
    assert count_ledger(service, wid) == 0


def test_demo_execution_cannot_target_other_organizations(case):
    service, order, _ = case
    with pytest.raises(ValueError, match="restricted to ORG-DEMO"):
        service.propose(Actor("ORG-PRODUCTION", "reviewer"), order.order_id, order.customer_id)


def test_clock_moved_backward_blocks_execution(case, monkeypatch):
    service, _, clock = case
    view = proposal(case)
    persist_approval_without_resume(service, view, monkeypatch)
    clock[0] -= timedelta(seconds=1)
    done = service.recover(ACTOR, view["workflow_id"])
    assert done["status"] == "stale"
    assert done["result"]["reason"] == "approval_clock_invalid"
    assert count_ledger(service, view["workflow_id"]) == 0


def require_native(service):
    with service.transaction():
        version = service.conn.execute("SELECT version() AS version").fetchone()["version"]
    if "PGlite" in version:
        pytest.skip("Native PostgreSQL required for SQL-error rollback and concurrent sockets")


@pytest.mark.parametrize("target", ["payload", "approval", "audit", "ledger"])
def test_database_enforces_immutability(case, target):
    import psycopg

    service, _, _ = case
    require_native(service)
    view = proposal(case)
    done = service.decide(ACTOR, view["workflow_id"], True, view["payload_sha256"])
    statement = {
        "payload": "UPDATE refundguard.workflows SET payload='{}' WHERE workflow_id=%s",
        "approval": "UPDATE refundguard.workflows SET expires_at=expires_at+interval '1 second' "
        "WHERE workflow_id=%s",
        "audit": "DELETE FROM refundguard.audit_events WHERE workflow_id=%s",
        "ledger": "DELETE FROM refundguard.demo_refund_ledger WHERE workflow_id=%s",
    }[target]
    with pytest.raises(psycopg.errors.RaiseException), service.transaction():
        service.conn.execute(statement, (view["workflow_id"],))
    assert service.view(ACTOR, view["workflow_id"]) == done
    assert count_ledger(service, view["workflow_id"]) == 1


@pytest.mark.parametrize("same_workflow", [True, False])
def test_concurrent_independent_sessions_cannot_double_refund(case, same_workflow):
    from concurrent.futures import ThreadPoolExecutor

    service, _, clock = case
    require_native(service)
    first = proposal(case)
    second = first if same_workflow else proposal(case)

    def approve(view):
        with workflow_connection(os.environ["TEST_DATABASE_URL"]) as conn:
            worker = ApprovalWorkflow(conn, service.ruleset, clock=lambda: clock[0])
            return worker.decide(ACTOR, view["workflow_id"], True, view["payload_sha256"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(approve, [first, second]))
    if same_workflow:
        assert [o["status"] for o in outcomes] == ["executed", "executed"]
        assert outcomes[0]["result"] == outcomes[1]["result"]
        assert count_ledger(service, first["workflow_id"]) == 1
    else:
        assert sorted(o["status"] for o in outcomes) == ["executed", "stale"]
        assert (
            count_ledger(service, first["workflow_id"])
            + count_ledger(service, second["workflow_id"])
            == 1
        )
