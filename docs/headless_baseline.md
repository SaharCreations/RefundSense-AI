# Headless dense retrieval baseline

Requires Python 3.12+, uv and a dedicated PostgreSQL database with pgvector.
Run from the repository root. The CLI reads environment variables, not `.env` files.

```bash
uv sync --locked --extra dev
uv run python scripts/download_model.py
export DATABASE_URL='postgresql://YOUR_USER:YOUR_PASSWORD@localhost:5432/refundguard'
uv run refundguard inspect
uv run refundguard --model-dir .cache/model ingest
uv run refundguard --model-dir .cache/model evaluate --split dev --k 1 3 5
```

Freeze changes before evaluating a fresh held-out split:

```bash
uv run refundguard --model-dir .cache/model evaluate --split heldout --k 1 3 5
uv run refundguard --model-dir .cache/model query 'What is the current opened-electronics restocking fee?' --k 5
```

The original held-out split has already been scored. Later reuse is regression testing, not unseen evaluation. `--split all` is a diagnostic. Global `--model-dir` and `--data-dir` options precede the command. The locked model directory reproduces the archived baseline; omitting it permits a default model download.

Queries default to current policies effective today. `--as-of 2026-10-06` fixes the date; `--scope all` permits explicit historical comparisons. Search returns evidence and provenance, not refund decisions.

The seven original Markdown documents produce 36 section/status chunks. Parsing retains source labels, heading paths, line spans, policy status/dates/version and hashes. Overlong sections fail instead of silently truncating. Immutable corpus/model snapshots are ingested transactionally; identical ingestion does not duplicate chunks. SQL parameters are bound, and expected evaluation labels never enter embedding or retrieval.

Ranking is exact cosine search in pgvector with stable tie-breaking. There is no hybrid/BM25 retrieval, reranker or approximate index. See [the frozen protocol](baseline_protocol.md) and [measured baseline](../BASELINE_RESULTS.md). Retrieval of an expected label does not establish answerability or citation correctness.
