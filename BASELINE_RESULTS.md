# Measured baseline results

Measured at 2026-10-06T23:28:55.969254+00:00. All numbers below are calculated from the archived per-question rankings, not estimates.

The unchanged starter pack produced **36 chunks from 7 policies**. All **30 questions** were evaluated with a fixed 20 development / 10 held-out split. Retrieval searched current and superseded policies together.

## Answerable questions

These are the primary retrieval metrics. Recall counts every expected section; MRR rewards the first relevant section.

| Split | Questions | Recall@1 | Recall@3 | Recall@5 | MRR@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Development | 16 | 53.12% | 75.00% | 81.25% | 0.6771 |
| Held out | 8 | 37.50% | 68.75% | 75.00% | 0.5729 |
| Combined diagnostic | 24 | 47.92% | 72.92% | 79.17% | 0.6424 |

## All supplied labels

These scores include the six abstention questions. Their gold sections describe escalation or partial evidence, so the combined score is a retrieval diagnostic, not answer quality or abstention accuracy.

| Split | Questions | Recall@5 | MRR@5 |
| --- | ---: | ---: | ---: |
| Development | 20 | 65.00% | 0.5417 |
| Held out | 10 | 65.00% | 0.5583 |
| Combined diagnostic | 30 | 65.00% | 0.5472 |

## Observed failures

- Development Q11 and Q12 ask for exact clause IDs. Neither expected section appears in the top five. This is concrete evidence for a later exact-clause or lexical-retrieval experiment; this baseline remains unchanged.
- Development Q21 is the retrieved prompt-injection question. Neither AS-1 nor AS-2 appears in its top five. The retrieval test does not establish prompt-injection resistance of a future LLM or action workflow.
- Held-out Q09 finds only one of its two required warranty sections; Q20 misses AS-3; Q24 misses AS-2. These are recorded findings, not targets used to tune this run.
- None of the six unanswerable queries retrieves RP-7 in the top five. Q29 retrieves RP-5, which is only half of its labeled evidence. Dense similarity alone is not a coverage or abstention detector.

## What is not measured

Citation correctness, abstention accuracy, deterministic rules-engine accuracy, refund safety, latency under load, and approval reliability are unmeasured. No LLM answers, customer/order SQL tables, refund rules engine, or execution workflow exists yet. Reports use null for the three planned accuracy metrics rather than assigning scores.

## Runtime and checks

- PostgreSQL 18.3 (PGlite 0.5.8) on wasm32-unknown-emscripten, compiled by emcc (Emscripten gcc/clang-like replacement + linker emulating GNU ld) 3.1.74 (1092ec30a3fb1d46b1782ff1b4db5094d3d06ae5), 32-bit
- pgvector 0.8.1; exact cosine search via psycopg.
- BAAI/bge-small-en-v1.5, FastEmbed 0.8.1, 384-dimensional normalized CPU embeddings. Model files and package versions are locked or fingerprinted.
- 25 tests passed, 1 skipped; lint passed.
- Native PostgreSQL could not start under workspace user restrictions and Docker was unavailable. The WASM PostgreSQL harness was used only for verification; application code still targets ordinary PostgreSQL + pgvector.
- The skipped SQL constraint-error rollback test remains enabled on native PostgreSQL. The PGlite socket wrapper returns no ROLLBACK response after SQL errors. A separate rollback test for a Python error midway through ingestion passed.
- PGlite uses one backend session; the verification harness restarted it between CLI processes to avoid retained prepared-statement names. Native PostgreSQL behavior, concurrency, and production readiness are not claimed.

## Evidence and next step

Raw reports, complete ranked chunks and provenance, model fingerprints, package/runtime versions, test output, and source hashes are in `reports/baseline_v1/`. `data/splits.json` and `docs/baseline_protocol.md` record the frozen protocol.

First rerun the integration suite on native PostgreSQL. Then use the development failures to choose one retrieval experiment. Keep the original measurements, expand the small synthetic dataset, and reserve fresh held-out questions if the existing held-out findings influence the next implementation. No hybrid search, BM25, or reranking was added.
