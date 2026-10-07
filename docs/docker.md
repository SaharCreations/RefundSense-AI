# Local Docker demo

Requires Docker Engine/Desktop with Compose v2, Python 3.12+, Node.js 20.9+ for verification tools, and uv. The application has three local services: Next.js, FastAPI and PostgreSQL + pgvector. PostgreSQL stores structured records, approvals, checkpoints and the synthetic ledger. There is no payment provider, Redis, queue, Kubernetes or extra application service.

From the project root:

```bash
python3 scripts/setup_demo.py
```

The script creates random local credential files once, builds/starts containers, downloads and hash-checks the frozen dense embedding artifacts, creates the existing SQL schemas, provisions missing SQL accounts and ingests policy sections. It preserves existing passwords, accounts, order facts, approvals and the database volume. It performs no approval or refund action.

Open http://127.0.0.1:3000. User IDs are `demo-support` and `demo-reviewer`. Their passwords are in `.local/support_password` and `.local/reviewer_password`; these private files are excluded from Git and Docker build contexts. View them locally when signing in. There are no public default passwords.

The seeded examples remain unchanged: `ORD-1002` / `CUST-1001` is the opened-electronics example. Its refund is $85 and fee $15 **only while it is inside the live 30-day window**. Seeded dates are fixed; later runs can legitimately become ineligible. The verification script creates fresh uniquely named test orders instead of overwriting the supplied examples.

Local web traffic is HTTP on loopback and uses the development image. Its session cookie is HttpOnly and SameSite=Strict. The production image uses Secure cookies and requires a configured HTTPS origin. The database is not published to the host; the API and web are bound to 127.0.0.1 only. Compose secrets avoid putting the database password in the YAML or container's plain environment configuration.

Optional experimental local explanation support:

```bash
python3 scripts/setup_demo.py --llm
```

This compiles the pinned CPU-only llama.cpp dependency and downloads the existing hash-pinned 1.5B model. It takes more time and disk space. The rejected 4B candidate is not promoted. Explanations are optional; eligibility and approval work without them.

Inspect/stop without deleting the database:

```bash
docker compose ps
docker compose logs --tail 100 api web
docker compose stop
```

Never use `down -v` to preserve approvals/orders. The initialization script is intended for a dedicated local demo database, not an existing customer database. Changing the local database password file does not rotate an already-initialized PostgreSQL volume's password.

## Images

`infra/docker/api.Dockerfile` installs the frozen Python lock, bakes the hash-checked dense model by default, and runs as UID 10001. `INSTALL_LLM=1` adds the optional CPU model runtime. `BAKE_EMBEDDINGS=0` is available for an explicit host-mounted verified model.

`frontend/Dockerfile` has development and production stages. The production stage contains the standalone Next.js output and runs as the node user. Neither image includes local secrets, model-comparison candidate weights, reports, Git history or browser credentials.

```bash
docker build -f infra/docker/api.Dockerfile -t refundguard-api .
docker build --target production -t refundguard-web frontend
```

Docker cannot run in the current editing workspace. Compose schema and Dockerfile structure were validated here; actual builds/startup remain a required CI gate. Do not describe these images as already run until that gate passes.
