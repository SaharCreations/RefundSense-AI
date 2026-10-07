# Verification and CI

The current measured end-to-end flow is a real browser -> actual Next.js route -> actual FastAPI -> psycopg -> PostgreSQL WASM -> persistent official LangGraph PostgreSQL checkpoints -> synthetic SQL ledger. Dense retrieval uses the real frozen embedding model and pgvector index. No mock API, order store or vector ranking is used in this flow. The browser simulates explicit reviewer confirmation for tests; the application still pauses for human approval.

Run against a disposable native PostgreSQL + pgvector database:

```bash
uv sync --locked --extra dev
npm ci --prefix frontend
npx --prefix frontend playwright install chromium
uv run --locked python scripts/download_model.py
export TEST_DATABASE_URL='YOUR_DISPOSABLE_POSTGRESQL_DSN'
.venv/bin/python scripts/verify_local_stack.py --with-retrieval --report-directory reports/local_latest
.venv/bin/python scripts/assert_test_report.py reports/local_latest/python-tests.xml --no-skips
```

The runner generates unique synthetic accounts and orders, runs the Python suite, starts separate backend and frontend processes, drives the real browser flow and then checks actual SQL amounts and ledger counts. Credentials are kept in a temporary private file and deleted in `finally`; they are never written to reports. Test order records/audits intentionally persist in the disposable database. It does not delete or reuse real customer records.

The browser cases verify execution of the reviewed payload, repeated-decision idempotency, persisted receipt after reload, SQL audit visibility, support-role refusal even through a direct authenticated request, rejection without refund, altered hash refusal, inability to execute pending proposals through recovery, and current pgvector evidence. Native Python tests additionally cover order changes, approval expiry, audit/proposal/ledger immutability and concurrent approvals.

If native PostgreSQL cannot run, the explicit fallback is:

```bash
npm ci --prefix verification/pglite
.venv/bin/python scripts/verify_local_stack.py --pglite --with-retrieval --report-directory reports/wasm_latest
```

This verification-only dependency is not part of the deployed application. PGlite runs PostgreSQL's single-user WASM build. It cannot establish native concurrent connection isolation or the seven SQL-error/trigger checks that explicitly skip there. Those checks remain pending until a native run completes. Do not replace the normal CI service with this fallback.

To create a silent walkthrough on fresh synthetic records, add `REFUNDGUARD_RECORD_DEMO=1` before the runner command. Playwright records a separate reference walkthrough: SQL assessment, pending exact payload, review checkbox and actual dense evidence. It does not approve the walkthrough's pending order. Functional test cases independently execute/reject their own generated synthetic orders.

## GitHub Actions

`.github/workflows/verify.yml` runs on pushes, pull requests and manual dispatch:

- Locked Python dependencies, all tests against native pgvector/PostgreSQL, then the live browser flow.
- Mandatory `--no-skips` XML gate: native-only checks cannot silently pass by being skipped.
- Strict TypeScript, production build, frontend boundary checks and the separate mock-API browser suite.
- AWS resource schema lint, Compose schema validation and container image builds.
- Evidence uploads on failure or success. No publishing, cloud deployment, account secrets or payment action is configured.

Actions are pinned to commits resolved from official GitHub tag metadata; `.github/actions.lock.json` records the tags and resolved commits. Credentials in the PostgreSQL service are deliberately public disposable CI fixture values, not deployed account credentials.

The workflow was syntax-checked with actionlint locally. It has not run on GitHub: no repository connection or public upload was performed. Its Docker and native database gates are prepared, not measured passing results.

Frontend fixture tests now write `reports/frontend_latest/` to preserve the archived `frontend_v1` evidence. Earlier evaluation, model-comparison, API and workflow reports remain frozen. New live-stack evidence is in `reports/completion_v1/`; it does not change Recall@k, MRR or explanation metrics.
