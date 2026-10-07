"""Persistent human approval and atomic, idempotent DEMO ledger execution.

No external payment gateway is connected. Only trusted application code may
supply actors or call this service; CLI identity flags are local demo inputs.
"""

import secrets
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID, uuid4

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .corpus import json_hash
from .orders import SCHEMA, read_order_customer
from .rules import Principal, RecordUnavailable, RefundRequest, Ruleset, assess_refund, exact_id

APPROVAL_TTL = timedelta(minutes=15)
SCHEMA_WORKFLOW = """
CREATE TABLE IF NOT EXISTS refundguard.workflows (
    workflow_id uuid PRIMARY KEY,
    organization_id text NOT NULL,
    created_by text NOT NULL,
    request jsonb NOT NULL,
    assessment jsonb NOT NULL,
    payload jsonb NOT NULL,
    payload_sha256 text NOT NULL,
    idempotency_key uuid NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN
        ('pending', 'approved', 'rejected', 'expired', 'stale', 'executed')),
    created_at timestamptz NOT NULL,
    approved_by text,
    approved_at timestamptz,
    expires_at timestamptz,
    result jsonb,
    CHECK (expires_at IS NULL OR expires_at = approved_at + interval '15 minutes')
);
CREATE TABLE IF NOT EXISTS refundguard.demo_refund_ledger (
    ledger_id uuid PRIMARY KEY,
    workflow_id uuid NOT NULL UNIQUE REFERENCES refundguard.workflows(workflow_id),
    idempotency_key uuid NOT NULL UNIQUE,
    payload_sha256 text NOT NULL,
    payload jsonb NOT NULL,
    executed_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS refundguard.audit_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workflow_id uuid NOT NULL REFERENCES refundguard.workflows(workflow_id),
    actor_id text NOT NULL,
    event text NOT NULL,
    occurred_at timestamptz NOT NULL,
    detail jsonb NOT NULL
);
CREATE OR REPLACE FUNCTION refundguard.immutable_proposal() RETURNS trigger AS $$
BEGIN
    IF (NEW.workflow_id, NEW.organization_id, NEW.created_by, NEW.request,
        NEW.assessment, NEW.payload, NEW.payload_sha256, NEW.idempotency_key, NEW.created_at)
       IS DISTINCT FROM
       (OLD.workflow_id, OLD.organization_id, OLD.created_by, OLD.request,
        OLD.assessment, OLD.payload, OLD.payload_sha256, OLD.idempotency_key, OLD.created_at)
    THEN RAISE EXCEPTION 'Approval proposal is immutable'; END IF;
    IF OLD.status <> 'pending' AND
        (NEW.approved_by, NEW.approved_at, NEW.expires_at) IS DISTINCT FROM
        (OLD.approved_by, OLD.approved_at, OLD.expires_at)
    THEN RAISE EXCEPTION 'Recorded approval is immutable'; END IF;
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status = 'pending' AND NEW.status IN ('approved', 'rejected')) OR
        (OLD.status = 'approved' AND NEW.status IN ('executed', 'stale', 'expired'))
    ) THEN RAISE EXCEPTION 'Invalid workflow transition'; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER immutable_workflow BEFORE UPDATE ON refundguard.workflows
FOR EACH ROW EXECUTE FUNCTION refundguard.immutable_proposal();
CREATE OR REPLACE FUNCTION refundguard.append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Append-only record';
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON refundguard.audit_events
FOR EACH ROW EXECUTE FUNCTION refundguard.append_only();
CREATE OR REPLACE TRIGGER ledger_append_only BEFORE UPDATE OR DELETE
ON refundguard.demo_refund_ledger FOR EACH ROW EXECUTE FUNCTION refundguard.append_only();
"""


@dataclass(frozen=True)
class Actor:
    organization_id: str
    user_id: str

    def __post_init__(self):
        exact_id(self.organization_id)
        exact_id(self.user_id)


class WorkflowState(TypedDict):
    workflow_id: str
    result: dict


def workflow_id(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Provide the exact workflow UUID")
    return value


class ApprovalWorkflow:
    """One serialized database session per service instance.

    Checkpointer and business transactions share the official saver's lock.
    Separate service instances serialize effects using PostgreSQL row locks.
    Call setup once as a migration, rather than during every future API request.
    """

    def __init__(self, conn, ruleset: Ruleset, clock=None):
        self.conn, self.ruleset = conn, ruleset
        self.clock = clock or (lambda: datetime.now(UTC))
        self.saver = PostgresSaver(conn)
        builder = StateGraph(WorkflowState)
        builder.add_node("approval", self._approval)
        builder.add_node("execute_demo", self._execute_node)
        builder.add_edge(START, "approval")
        builder.add_edge("approval", "execute_demo")
        builder.add_edge("execute_demo", END)
        self.graph = builder.compile(checkpointer=self.saver)

    def setup(self):
        with self.saver.lock:
            self.conn.execute(SCHEMA)
            self.conn.execute(SCHEMA_WORKFLOW)
        self.saver.setup()

    def now(self):
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("Trusted application clock must return timezone-aware UTC time")
        return now.astimezone(UTC)

    @contextmanager
    def transaction(self):
        with self.saver.lock, self.conn.transaction():
            yield

    @staticmethod
    def config(wid):
        return {"configurable": {"thread_id": wid}}

    def _row(self, wid, actor=None, lock=False):
        wid = workflow_id(wid)
        sql = "SELECT * FROM refundguard.workflows WHERE workflow_id=%s"
        params = [wid]
        if actor:
            sql += " AND organization_id=%s"
            params.append(actor.organization_id)
        if lock:
            sql += " FOR UPDATE"
        row = self.conn.execute(sql, params).fetchone()
        if row is None:
            raise RecordUnavailable("Workflow is not available in the authorized organization")
        if json_hash(row["payload"]) != row["payload_sha256"]:
            raise ValueError("Stored payload integrity check failed")
        if row["payload"]["idempotency_key"] != str(row["idempotency_key"]):
            raise ValueError("Stored idempotency binding check failed")
        return row

    def _audit(self, row, actor_id, event, detail=None):
        self.conn.execute(
            "INSERT INTO refundguard.audit_events "
            "(workflow_id, actor_id, event, occurred_at, detail) VALUES (%s,%s,%s,%s,%s)",
            (
                row["workflow_id"],
                actor_id,
                event,
                self.now(),
                Jsonb({"payload_sha256": row["payload_sha256"], **(detail or {})}),
            ),
        )

    @staticmethod
    def _view(row):
        return {
            "workflow_id": str(row["workflow_id"]),
            "status": row["status"],
            "exact_execution_payload": row["payload"],
            "payload_sha256": row["payload_sha256"],
            "approval_ttl_seconds": int(APPROVAL_TTL.total_seconds()),
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "assessment": row["assessment"],
            "result": row["result"],
            "demo_only": True,
        }

    def view(self, actor, wid):
        with self.transaction():
            return self._view(self._row(wid, actor))

    def propose(self, actor, order_id, customer_id, reason="standard_return"):
        if actor.organization_id != "ORG-DEMO":
            raise ValueError("Demo ledger proposals are restricted to ORG-DEMO")
        req = RefundRequest(order_id, customer_id, self.now().date(), reason)
        principal = Principal(actor.organization_id)
        wid, key = str(uuid4()), str(uuid4())
        with self.transaction():
            order, customer = read_order_customer(self.conn, principal, req)
            assessment = assess_refund(principal, customer, order, req, self.ruleset)
            if assessment["decision"] != "eligible":
                return {"status": "assessment_blocked", "assessment": assessment}
            payload = {
                "execution_target": "demo_ledger",
                "idempotency_key": key,
                "refund": assessment["candidate_payload"],
            }
            request_data = {**asdict(req), "requested_on": req.requested_on.isoformat()}
            self.conn.execute(
                """INSERT INTO refundguard.workflows
                (workflow_id, organization_id, created_by, request, assessment, payload,
                 payload_sha256, idempotency_key, status, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s)""",
                (
                    wid,
                    actor.organization_id,
                    actor.user_id,
                    Jsonb(request_data),
                    Jsonb(assessment),
                    Jsonb(payload),
                    json_hash(payload),
                    key,
                    self.now(),
                ),
            )
            row = self._row(wid)
            self._audit(row, actor.user_id, "proposed")
        # Proposal survives even if checkpoint creation fails; recover() restarts it.
        self.graph.invoke({"workflow_id": wid}, self.config(wid), durability="sync")
        return self.view(actor, wid)

    def _approval(self, state):
        wid = state["workflow_id"]
        with self.transaction():
            prompt = self._view(self._row(wid))
        response = interrupt(prompt)
        # Resume data never grants permission. Only a durable server-side decision can.
        if response != {"workflow_id": wid}:
            raise ValueError("Invalid approval receipt")
        with self.transaction():
            if self._row(wid)["status"] == "pending":
                raise ValueError("A durable human decision is required before resuming")
        return {}

    def decide(self, actor, wid, approved, payload_sha256):
        if type(approved) is not bool:
            raise ValueError("Human approval must be an explicit boolean")
        with self.transaction():
            row = self._row(wid, actor, lock=True)
            if not isinstance(payload_sha256, str) or not secrets.compare_digest(
                payload_sha256, row["payload_sha256"]
            ):
                raise ValueError("Approval must confirm the exact displayed payload hash")
            if row["status"] == "pending":
                status = "approved" if approved else "rejected"
                now = self.now()
                self.conn.execute(
                    """UPDATE refundguard.workflows SET status=%s, approved_by=%s,
                    approved_at=%s, expires_at=%s WHERE workflow_id=%s""",
                    (
                        status,
                        actor.user_id,
                        now if approved else None,
                        now + APPROVAL_TTL if approved else None,
                        wid,
                    ),
                )
                self._audit(row, actor.user_id, status)
            elif (row["status"] == "rejected" and approved) or (
                row["status"] in {"approved", "executed"} and not approved
            ):
                raise ValueError("A recorded decision cannot be reversed; create a new proposal")
        return self.recover(actor, wid)

    def recover(self, actor, wid):
        # Authorization precedes every access to a checkpoint, including restart recovery.
        view = self.view(actor, wid)
        snapshot = self.graph.get_state(self.config(wid))
        if not snapshot.values:
            self.graph.invoke({"workflow_id": wid}, self.config(wid), durability="sync")
            snapshot = self.graph.get_state(self.config(wid))
        if view["status"] == "pending":
            return self.view(actor, wid)
        if snapshot.next:
            has_interrupt = any(task.interrupts for task in snapshot.tasks)
            command = Command(resume={"workflow_id": wid}) if has_interrupt else None
            self.graph.invoke(command, self.config(wid), durability="sync")
        return self.view(actor, wid)

    def _execute_node(self, state):
        return {"result": self._execute(state["workflow_id"])}

    def _execute(self, wid):
        with self.transaction():
            row = self._row(wid, lock=True)
            if row["status"] != "approved":
                return row["result"] or {"status": row["status"], "executed": False}
            now = self.now()
            if not row["approved_at"] or now < row["approved_at"]:
                return self._block(row, "stale", "approval_clock_invalid")
            if not row["expires_at"] or now >= row["expires_at"]:
                return self._block(row, "expired", "approval_expired")
            request_data = dict(row["request"])
            request_data["requested_on"] = now.date()
            req = RefundRequest(**request_data)
            principal = Principal(row["organization_id"])
            # Both order and customer stay locked until ledger/order/audit commit together.
            self.conn.execute(
                """SELECT o.order_id FROM refundguard.orders o
                JOIN refundguard.customers c ON c.organization_id=o.organization_id
                    AND c.customer_id=o.customer_id
                WHERE o.organization_id=%s AND o.order_id=%s AND o.customer_id=%s
                FOR UPDATE OF o,c""",
                (principal.organization_id, req.order_id, req.customer_id),
            ).fetchone()
            try:
                order, customer = read_order_customer(self.conn, principal, req)
            except RecordUnavailable:
                return self._block(row, "stale", "live_record_unavailable")
            live = assess_refund(principal, customer, order, req, self.ruleset)
            original = row["assessment"]
            if (
                live["decision"] != "eligible"
                or live["candidate_payload"] != row["payload"]["refund"]
                or live["ruleset_fingerprint"] != original["ruleset_fingerprint"]
                or live["snapshot"]["order_revision"] != original["snapshot"]["order_revision"]
                or live["snapshot"]["customer_revision"]
                != original["snapshot"]["customer_revision"]
            ):
                return self._block(row, "stale", "live_state_or_rules_changed")
            # Unique keys plus workflow/order locks make retries and competing approvals safe.
            ledger_id = str(uuid4())
            self.conn.execute(
                """INSERT INTO refundguard.demo_refund_ledger
                (ledger_id, workflow_id, idempotency_key, payload_sha256, payload, executed_at)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                (
                    ledger_id,
                    wid,
                    row["idempotency_key"],
                    row["payload_sha256"],
                    Jsonb(row["payload"]),
                    now,
                ),
            )
            refund = row["payload"]["refund"]
            self.conn.execute(
                """UPDATE refundguard.orders SET refunded_minor=refunded_minor+%s,
                refund_state='refunded' WHERE organization_id=%s AND order_id=%s""",
                (refund["refund_amount_minor"], principal.organization_id, req.order_id),
            )
            result = {
                "status": "executed",
                "demo_only": True,
                "ledger_id": ledger_id,
                "idempotency_key": str(row["idempotency_key"]),
                "payload_sha256": row["payload_sha256"],
                "refund_amount_minor": refund["refund_amount_minor"],
                "currency": refund["currency"],
                "executed_at": now.isoformat(),
            }
            self.conn.execute(
                "UPDATE refundguard.workflows SET status='executed', result=%s "
                "WHERE workflow_id=%s",
                (Jsonb(result), wid),
            )
            self._audit(row, "system:demo-ledger", "executed", {"ledger_id": ledger_id})
            return result

    def _block(self, row, status, reason):
        result = {"status": status, "reason": reason, "executed": False}
        self.conn.execute(
            "UPDATE refundguard.workflows SET status=%s, result=%s WHERE workflow_id=%s",
            (status, Jsonb(result), row["workflow_id"]),
        )
        self._audit(row, "system:demo-ledger", status, {"reason": reason})
        return result


@contextmanager
def workflow_connection(url):
    with psycopg.connect(
        url, autocommit=True, row_factory=dict_row, prepare_threshold=None, connect_timeout=10
    ) as conn:
        yield conn
