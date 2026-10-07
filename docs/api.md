# FastAPI milestone

The API exposes the existing PostgreSQL order reads, deterministic assessments,
dense policy retrieval, and persistent LangGraph approval workflow. The later optional extractive explanation endpoints are documented in `docs/explanations.md`; the measured dense baseline remains unchanged.

Authentication is implemented with locally provisioned SQL accounts, Argon2id
password hashes, and revocable opaque bearer sessions. Organization and role come
from SQL on each authenticated request. No client-selected organization, role,
approval timestamp, assessment date, refund amount, or execution payload is accepted.
The CLI remains a trusted local administration/development interface; it is not
exposed through HTTP.

## Start locally

Run from the project root with Python 3.12+, the locked dependencies, and a
dedicated PostgreSQL database. Set `DATABASE_URL` explicitly; `.env` is not loaded
automatically. For the later container setup, see `docs/docker.md`.

```bash
uv sync --locked --extra dev
uv run refundguard seed-demo
uv run refundguard workflow-init
uv run refundguard auth-init
uv run refundguard auth-create-user --organization-id ORG-DEMO --user-id demo-support --role support
uv run refundguard auth-create-user --organization-id ORG-DEMO --user-id demo-reviewer --role reviewer
```

Provisioning prompts for a password twice without echoing it. Choose 12–128
characters. There are no seeded/default credentials, public registration, or
client-accessible role changes. Repeated provisioning refuses to overwrite an
existing account. For scripted provisioning, set the transient environment
variable `REFUNDGUARD_BOOTSTRAP_PASSWORD` and unset it after the command. Do not
put passwords in command arguments or commit them to this project.

For policy search, download/verify the pinned model and ingest the original corpus
using the README instructions. Then point the API at that explicit local folder:

```bash
export REFUNDGUARD_MODEL_DIR='.cache/model'
uv run uvicorn refundguard.api:create_app --factory --host 127.0.0.1 --port 8000
```

The interactive API docs are at `http://127.0.0.1:8000/docs`. Log in through the
`POST /api/v1/auth/login` JSON operation. Copy its `access_token`, click
**Authorize**, and paste the token into the bearer field. Tokens must be kept
private. The machine-readable schema is at `/openapi.json`; a captured schema is
included under `reports/api_v1/openapi.json` for frontend work.

No embedding download happens for assessment or workflow operations. Without an
explicit model folder, policy search returns `503 policy_search_not_configured`.
A mismatching or incomplete database collection returns `503 policy_index_not_ready`.
The search path checks the corpus/model fingerprint against the ingested index.
Inference is serialized within an API process; SQL sessions are scoped to requests.

## HTTP contract

| Method and path | Permission | Purpose |
| --- | --- | --- |
| `GET /health` | Public | Database liveness; no customer facts |
| `POST /api/v1/auth/login` | Public | Username/password JSON → bearer session |
| `GET /api/v1/auth/me` | Signed in | Current SQL identity, organization, role |
| `POST /api/v1/auth/logout` | Signed in | Revoke the current session |
| `POST /api/v1/assessments` | Support or reviewer | Read exact SQL IDs and calculate eligibility/amount |
| `POST /api/v1/workflows` | Support or reviewer, ORG-DEMO | Create an eligible proposal and pause before execution |
| `GET /api/v1/workflows/{wid}` | Same organization | Show exact immutable payload and status |
| `POST /api/v1/workflows/{wid}/decisions` | Reviewer, same organization | Confirm payload hash and approve/reject |
| `POST /api/v1/workflows/{wid}/recover` | Reviewer, same organization | Recover persisted approval/action state |
| `GET /api/v1/workflows/{wid}/audit` | Reviewer, same organization | Read ordered action audit events |
| `POST /api/v1/policy/search` | Support or reviewer, ORG-DEMO | Retrieve current policy evidence; cannot authorize execution |

Assessment/proposal JSON:

```json
{"order_id": "ORD-1002", "customer_id": "CUST-1001", "reason": "standard_return"}
```

Supported reason values are `standard_return`, `damaged_on_arrival`, and `warranty`.
Warranty produces the rules engine's separate-review outcome. Noneligible proposals
return `assessment_blocked` with the assessment; no approval workflow is created.
An eligible proposal returns the full immutable `exact_execution_payload`, hash,
workflow UUID, assessment/citations, and `pending` status. Monetary values are cents.

Review the complete payload before sending a decision:

```json
{"approved": true, "payload_sha256": "COPY_THE_EXACT_64_CHARACTER_HASH_FROM_THE_PROPOSAL"}
```

`approved` must be a JSON boolean: strings, numbers, and null are rejected. Set it
to `false` to reject. Extra request fields are forbidden. Confirmation cannot edit
an amount or destination. Only server-side deterministic code creates the payload.
Approval resumes LangGraph and executes the synthetic demo ledger if live
revalidation succeeds. There is no separate bypass/execute route, raw checkpoint
route, or automatic approval path. Recovering a still-pending workflow cannot grant
approval. The workflow expiry, revalidation, atomicity, and idempotency semantics
are documented in `approval_workflow.md`.

A repeated decision/recovery returns the original receipt after execution. It
cannot renew approval or create another ledger entry. Proposal creation currently
creates a new workflow for each call; if a create response is lost, another proposal
can be created, but live order locks/rules prevent both from executing. The action
idempotency key belongs to the immutable workflow payload, not a caller-selected
amount or arbitrary HTTP header.

Search JSON:

```json
{"question": "What is the current opened electronics restocking fee?", "k": 5}
```

`k` is an integer from 1–20. Questions are capped at 2,000 characters and the existing
512-token model limit; long inputs fail instead of silently truncating. Scope and
as-of date are server-controlled (`current`, today's UTC date). The API's one
synthetic company-policy corpus is restricted to ORG-DEMO. Historical retrieval
remains available through the evaluation CLI, not customer-facing API search.
Returned chunks include section provenance, ranks, and similarity. They remain
untrusted reference text and do not enter the eligibility or approval code as
instructions. These are retrieved excerpts, not AI-generated answers or a citation
correctness measurement.

## Session and permission behavior

- Passwords are salted Argon2id hashes; password parameters are rehashed on a
  successful login when needed. Unknown/disabled users and wrong passwords return
  the same error; unknown users also perform dummy password verification.
- Tokens contain 256 random bits. SQL stores only their SHA-256 digest, not the
  raw bearer token. Sessions expire after 8 hours and can be revoked by logout.
- Every request joins the session to the live account. Disabled users lose access;
  SQL role changes apply on the next request without reissuing tokens.
- PostgreSQL persists a five-attempt login window per exact username. Further
  attempts receive 429 until its 15-minute window resets. Successful login resets
  that counter. This is a basic account throttle, not a complete traffic/DoS defense.
- Support users cannot grant/reject approval, recover approved actions, or read
  audit records. Organization checks occur before checkpoint/audit access.
- API validation omits raw values and redacts unknown field names; passwords are
  not echoed in validation errors. Responses use `Cache-Control: no-store`.

## Errors

| Status | Meaning |
| --- | --- |
| `401` | Missing/invalid credentials, expired/revoked session, or disabled account |
| `403` | Reviewer permission or demo organization required |
| `404` | Exact record/workflow unavailable in the authenticated organization |
| `409` | Payload confirmation mismatch or a conflicting recorded decision |
| `422` | Invalid fields/types, noncanonical UUID, or model token limit exceeded |
| `429` | Login attempt window exhausted |
| `503` | Database unavailable, policy search unconfigured, or index not ready |

Expired/stale approvals return the workflow's terminal status and blocking reason
without execution. Database/internal failures return generic error codes without
SQL statements, connection credentials, or traceback details in the HTTP response.

## Verification and remaining gates

The full suite has **125 passing tests and 7 native-only checks skipped**. This
milestone adds **31 passing API checks** (29 HTTP/SQL integration cases and 2
configuration/error-boundary cases). Evidence is in `reports/api_v1/tests.xml`.

`scripts/verify_api_http.py` also ran **18 real HTTP checks through two separate
Uvicorn processes**, using generated synthetic accounts and orders. After server
restart, the same bearer session and pending LangGraph interrupt still worked.
The reviewer approved one $85.00 demo refund; repeated approval/recovery returned
the same receipt, with exactly one ledger row. It also exercised the real local
dense embedding model and pgvector policy search. Generated passwords and bearer
values are excluded from its report. Raw output is in `reports/api_v1/http_smoke.json`.

Run only against a disposable test database with the pinned model/index ready:

```bash
export TEST_DATABASE_URL="$DATABASE_URL"
uv run python scripts/verify_api_http.py
uv run pytest -q
```

The database runtime remains PostgreSQL 18.3 compiled to WASM via PGlite 0.5.8,
with pgvector and psycopg. Its socket wrapper was configured to accept 16 connections
so sequential API connection teardown does not reject the next connection. This
verification runtime is not an application dependency. Native PostgreSQL trigger,
SQL-error rollback, and independent-session concurrency gates are still pending;
seven tests intentionally remain skipped on PGlite. Prior retrieval/rules/workflow
reports remain unchanged. No new retrieval, citation, or abstention metrics are
claimed here.

This is a local portfolio demo, with loopback HTTP for development. Public hosting
requires HTTPS, deployment secrets, database least privilege and native concurrency
verification. Self-service account recovery, MFA, broader login/traffic protection,
and expired-session cleanup are not implemented. The browser login interface and
its session handling will be added with Next.js. Real payment integration remains
separate; the API writes only synthetic demo ledger/order effects in ORG-DEMO.

Implementation references: [FastAPI security documentation](https://fastapi.tiangolo.com/tutorial/security/)
and [argon2-cffi password hashing](https://argon2-cffi.readthedocs.io/en/stable/howto.html).
The API uses opaque SQL sessions, not the JWT implementation in FastAPI's tutorial.

## Optional AI explanations

The fifth milestone adds authenticated `/api/v1/policy/answer` and
`/api/v1/assessments/explain`. See [explanations.md](explanations.md) for
model setup, strict quotation validation, metric definitions and limitations.
These endpoints cannot grant approval or execute a refund.
