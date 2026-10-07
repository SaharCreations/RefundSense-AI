# Contributing

Use Python 3.12+ and the committed `uv.lock`; use `npm ci` with the frontend lockfile. Start with the commands in [README.md](README.md) and [verification.md](docs/verification.md). Integration tests require a disposable PostgreSQL + pgvector database. Never point test tooling at customer data.

Keep SQL authoritative for customer/order facts and Python authoritative for eligibility, dates, fees and money. LangGraph is limited to persistent approval/action state. Review must bind the exact execution payload; execution must revalidate live state. Do not bypass expiry, idempotency, permissions or audit guarantees.

Preserve original policy/questions and archived evidence. New evaluation runs belong in a new report directory. State denominators, split usage, abstentions and skips. The original held-out split has already been observed. Add hybrid retrieval or reranking only when the dense baseline demonstrates a concrete need.

For behavior changes, run relevant tests and document measured evidence and remaining gates. Never commit credentials, model weights, database dumps, installed environments or private order data. Use synthetic fixtures. No Go, Redis, SQS, Kubernetes or additional application services are part of this design.

Use the pull request template to explain the concrete behavior change and verification. The repository currently has no selected license; obtain the owner's terms before redistributing it.
