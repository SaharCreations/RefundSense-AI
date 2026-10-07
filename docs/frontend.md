# Review dashboard

The `frontend/` application uses Next.js 16.4.0, React 19.3.0 and strict TypeScript. It connects to the existing FastAPI application. PostgreSQL, rules, retrieval and LangGraph remain in Python; the Next.js route handler is a same-origin HTTP boundary, with no business decisions or new database.

## Run locally

Install Node.js 20.9 or later (verification used Node.js 24.19.0). Start the existing backend using the setup in `docs/api.md` (including SQL schema and trusted CLI-created users). No default user or password is supplied.

```bash
uv run uvicorn refundguard.api:create_app --factory --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
cd frontend
npm ci
cp .env.example .env.local
NEXT_TELEMETRY_DISABLED=1 npm run dev
```

Open `http://127.0.0.1:3000`. Configure `REFUNDGUARD_API_URL` server-side if the backend uses a different origin. Dense policy search requires the existing populated index and `REFUNDGUARD_MODEL_DIR`; explanations additionally require the existing pinned local LLM configuration. Neither feature downloads models from the dashboard.

A production build can be checked with `npm run build`. Production serving requires HTTPS because the session cookie is Secure in production. Set `REFUNDGUARD_WEB_ORIGIN` to the exact public HTTPS origin for production, including behind a reverse proxy; production requests fail closed if it is missing. `REFUNDGUARD_API_URL` must be an origin without path, query, user credentials or fragment. Do not use a `NEXT_PUBLIC_` variable for backend configuration. Hosting and AWS deployment remain future work.

## User flow

1. Sign in using an administrator-provisioned SQL account.
2. Enter exact order and customer IDs and a reason. The UI does not trim, infer or auto-populate identifiers. The backend scopes records to the authenticated organization.
3. Inspect the deterministic eligibility, integer-cent amounts, reason and source section references.
4. For an eligible assessment, create an approval request. The backend reassesses live state while creating the request; a blocked response replaces the old assessment.
5. Review the workflow's complete immutable JSON execution payload, payment reference, idempotency key and SHA-256. A reviewer must explicitly check the confirmation box before approving or rejecting. The decision contains only the approved boolean and the displayed server hash. Amounts and identities are not submitted by the UI.
6. The existing backend revalidates live facts and performs the synthetic ledger action. No external payment provider is configured.
7. Reload a saved workflow by its exact UUID to inspect persisted status. Reviewer accounts can view audit events and recover already-approved workflows.

Pending proposals do not display a fabricated expiry. The displayed validity period starts when approval is granted. If an expiry is present, the UI disables decisions once it passes; the backend remains authoritative. Refresh, changing the selected workflow and any submitted decision clear the review confirmation. A network error never causes an automatic action retry; refresh the persisted server status first.

## Session and action boundaries

The server route holds the backend bearer token in an HttpOnly, SameSite=Strict cookie, with Secure enabled in production. No token, order, workflow or password is persisted in localStorage or sessionStorage. The login response to JavaScript contains only `authenticated: true`. Backend SQL checks organization, role, account status and session validity on every protected request. UI role restrictions are a convenience, not authorization.

POST requests require the exact same Origin, including login and logout. A fixed method/path allowlist, no query passthrough, bounded streamed JSON request bodies, fixed server-configured upstream, redirect rejection and no-store responses keep this from becoming a generic proxy. Incoming browser Authorization headers are ignored. Logout revokes the backend session; a backend 401 clears the cookie and sensitive UI state. Backend errors are shown as concise messages; inputs and credentials are not logged by application code.

Policy retrieval displays current ranked section text as escaped React text. Retrieved instructions and markup cannot trigger an action. The optional local LLM explanation is labeled experimental and reference-only; abstention does not hide the deterministic assessment. Its output never feeds the execution payload or approval request.

## Verification

```bash
cd frontend
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

The browser suite starts the actual Next.js application and a small HTTP contract fixture on ports 3008 and 8108. Its synthetic records, payment reference, quotes and audit event are explicitly fixtures. These checks do **not** execute FastAPI, PostgreSQL, pgvector, LangGraph or the LLM. They cannot establish fresh SQL integration or model metrics. Previously measured backend and retrieval reports are retained unchanged. See `reports/frontend_v1/` and `FRONTEND_RESULTS.md` for this milestone's measured checks.

Official API references checked during implementation:
- https://nextjs.org/docs/app/api-reference/file-conventions/route
- https://nextjs.org/docs/app/api-reference/functions/cookies
