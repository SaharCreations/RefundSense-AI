# Persistent human approval: demo milestone

The headless workflow uses LangGraph only for the stateful approval/action path.
The existing retrieval code and deterministic assessments remain independent.
`PostgresSaver` stores interrupts, state, and pending node writes in PostgreSQL.
All graph invocations use synchronous durability. No memory checkpointer is used
in this implementation or its database tests.

Execution in this milestone means an atomic **demo ledger entry and synthetic
order update**. There is no payment gateway or real money movement. Proposals
are restricted to `ORG-DEMO`. The original five seeded CLI orders are not
changed by the verification script: it creates unique synthetic test records.

## Local commands

Install with `uv sync --locked --extra dev`, set `DATABASE_URL` to a dedicated
PostgreSQL database, and run from the project root. These workflow commands do
not download a model or invoke an LLM.

```bash
uv run refundguard seed-demo
uv run refundguard workflow-init
uv run refundguard workflow-propose \
  --organization-id ORG-DEMO --user-id demo-reviewer \
  --order-id ORD-1002 --customer-id CUST-1001
```

The last command persists the proposal and pauses at a LangGraph interrupt.
Its output contains `workflow_id`, `exact_execution_payload`, and
`payload_sha256`. Read the entire payload: destination, idempotency key,
organization, exact order/customer IDs, amount, restocking fee, currency,
payment method, and original payment reference. Amounts and fees are integer
cents; the calculation conventions are in `rules_engine.md`.

Inspect a proposal after restarting the process:

```bash
uv run refundguard workflow-view \
  --organization-id ORG-DEMO --user-id demo-reviewer \
  --workflow-id EXACT_UUID_FROM_OUTPUT
```

After reviewing it, explicitly choose `approve` or `reject` and copy the
unchanged payload hash. Approval executes the synthetic demo refund immediately
if revalidation succeeds; rejection executes nothing.

```bash
uv run refundguard workflow-decide \
  --organization-id ORG-DEMO --user-id demo-reviewer \
  --workflow-id EXACT_UUID_FROM_OUTPUT \
  --decision approve --payload-sha256 EXACT_HASH_FROM_OUTPUT
```

For process/checkpoint failures, repeat the same decision or run:

```bash
uv run refundguard workflow-recover \
  --organization-id ORG-DEMO --user-id demo-reviewer \
  --workflow-id EXACT_UUID_FROM_OUTPUT
```

CLI organization and reviewer flags are **local demo inputs, not authentication**.
The FastAPI milestone now derives identities and reviewer permissions from SQL
authentication; see `api.md`. Do not expose arbitrary graph thread access or approval
tools to an LLM. The graph and database are trusted application internals.
The CLI is still a trusted local demo interface, not the HTTP authentication boundary.

## Approval and execution guarantees

- The proposal, request, assessment, payload, hash, and idempotency key are
  immutable. An amount cannot be edited during approval; start a new proposal.
- The decision is recorded in SQL before graph resume. Resume input is a receipt,
  not authority to approve; the graph checks the durable decision independently.
- Approval expires 15 minutes after its first grant. At the expiry instant it is
  invalid. Retrying cannot renew it. Application time is UTC and comes from a
  trusted clock; callers cannot supply an approval timestamp or assessment date.
- Immediately before execution, the workflow locks its row plus the live order
  and customer rows, reloads their facts, and reruns deterministic rules using
  today's UTC date. Order/customer revision changes, policy/rules fingerprint
  changes, ineligibility, unavailable records, or a changed payload invalidate
  approval. The same monetary amount with a changed revision still requires a
  new proposal. A deadline passing overnight also blocks execution.
- The demo ledger insert, order balance/state change, workflow receipt, and
  execution audit event commit in one transaction. A failure before commit rolls
  them back. A failure after commit returns the same receipt on recovery.
- Workflow and ledger keys are unique; each workflow has one server-generated
  idempotency key. Row locks serialize competing approvals for the same order.
  A second proposal cannot spend an already refunded order.
- Audit and ledger rows have append-only database triggers. Events record the
  actor, time, immutable payload hash, and proposal/approval/rejection/execution
  or blocking reason. This is an application audit trail, not tamper-proof
  storage against a database administrator.

Each service instance uses one PostgreSQL session. Business transactions and
the official checkpointer share the saver's lock, avoiding simultaneous use of
that session. Future request handlers should create separate service instances;
PostgreSQL row locks protect effects across those sessions. Run schema setup as
a migration, not on each API request.

The SQL workflow row is the durable decision/execution authority. LangGraph
tracks the interrupted/resumable path. Initial checkpoint failure can recover a
persisted pending proposal. A committed ledger receipt survives an interrupted
final checkpoint, and recovery completes the graph without executing again.

## Verification evidence and limits

The full suite run archived in `reports/workflow_v1/tests.xml` passed **94 tests**
and skipped **7 native-only checks**. Of these, **23 workflow tests passed**;
6 additional workflow checks require native PostgreSQL. The previous retrieval
and rules evidence remains unchanged.

The run used PostgreSQL 18.3 compiled to WASM (PGlite 0.5.8), via psycopg and the
unmodified official `PostgresSaver`, including its migrations and pipeline path.
The verification harness is not an application dependency. Neither native
PostgreSQL nor Docker is available in this workspace.

`scripts/verify_workflow_restart.py` ran six independent CLI subprocesses against
persisted PostgreSQL state: initialize, propose, inspect, approve, recover, and
replay approval. It confirmed one $85.00 ledger entry, one order update, three
ordered audit events, and identical retry receipts. Decisions in this script are
explicitly synthetic test approvals. Raw evidence is in
`reports/workflow_v1/process_restart.json`.

Run it only against a disposable test database:

```bash
export TEST_DATABASE_URL="$DATABASE_URL"
uv run python scripts/verify_workflow_restart.py
uv run pytest -q
```

`TEST_DATABASE_URL` also enables the native integration tests. Four database
trigger/error-rollback checks and two concurrent independent-session approval
checks are intentionally skipped on PGlite, whose socket wrapper is not suitable
for those cases. One prior ingestion SQL-error rollback check is also skipped.
**Native PostgreSQL concurrency, trigger enforcement, and SQL-error rollback
remain mandatory verification gates before deployment.** Sequential retry and
Python-error rollback checks passed; they do not substitute for concurrency tests.

There is no external payment integration. A real gateway needs its own stable
idempotency key, durable attempt/result recording, and reconciliation for a
payment accepted remotely before a local commit fails. Do not swap a network
payment call into the demo transaction and assume the current atomicity guarantee
will cover it. SQL authentication and FastAPI are now implemented for the local demo in `api.md`.
The frontend, Docker/CI, and cloud deployment remain later milestones. No new retrieval scores, citation correctness, or
abstention metrics are claimed by this workflow milestone.
