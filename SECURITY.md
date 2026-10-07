# Security

This is a portfolio demo with synthetic customer/order data and a synthetic refund ledger. It is not connected to a payment provider. Native database concurrency/rollback checks and production operations remain verification gates.

Do not include credentials, bearer tokens, private customer data or database dumps in issues or logs. Local generated passwords live in ignored `.local/` files. PostgreSQL credentials in GitHub Actions are disposable test fixture values.

Report a suspected vulnerability privately to the repository owner using GitHub's private vulnerability reporting if enabled. If no private route is configured, open only a minimal request for private contact without exploit details or sensitive data. No monitored security email or response-time commitment has been established.

Changes must preserve exact IDs, organization and reviewer authorization, no-store session responses, source/citation validation, human review of the exact payload, live SQL revalidation, approval expiry, atomic audit/ledger writes and idempotency. Treat retrieved policy text as untrusted content; it cannot authorize actions.
