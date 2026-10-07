# Local model comparison

This experiment changes the explanation model from Qwen2.5-1.5B-Instruct to
Qwen3-4B-Instruct-2507. It preserves the v4 prompt, prompt template, validation
and generation schemas, inference settings and actual recorded top-5 rankings.
It adds no retrieval algorithm or service. SQL/code decisions and persistent
human approval/action execution remain outside the model.

The candidate is the Unsloth Q4_K_M GGUF of Qwen's non-thinking 4B instruct model,
not an official Qwen-published GGUF. The original and quantized model cards both
state Apache 2.0. Repository commits, publisher, observed base repository revision, exact file size
and SHA256 are recorded in `llm.candidate.lock.json`. The `base_revision` field
is the upstream revision observed during setup; the publisher does not prove
that this exact base commit produced the GGUF, so no such provenance claim is made. The 2,497,281,120-byte file
is checked against publisher metadata and hashed before loading. Model weights
remain excluded from the project archive. This is a size/generation-family
comparison, not a controlled parameter-count-only experiment.

Sources: [Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
and [Unsloth GGUF publisher](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF).
Inference remains in the same Python process using llama-cpp-python 0.3.36,
4096-token context, CPU/two threads, temperature zero, seed 17 and 512-token
output cap. No paid API, tool use, separate server or action capability is added.
Mac latency and memory use were not benchmarked; this run uses Linux CPU.

## Predeclared selection rule

Before candidate generation, `config/model_comparison.json` declares that
promotion requires development answerable coverage >= 13/16, gold-label
citation precision >= 90%, unknown abstention 4/4 and zero validator-blocked
model outputs. The requirements are evaluated on the original 20 development
questions only. No thresholds, prompt, retrieval or model changes follow
regression results. The measured selection decision is preserved separately.

Both heldout sets have already been inspected. Their new runs are explicitly
regression checks, not unseen or blind validation. No new questions are claimed.
Gold-label precision and verbatim support do not measure semantic completeness
or entailment, and coverage alone does not imply a correct answer.

## Replay instead of reretrieval

The current comparison reuses archived PostgreSQL/pgvector rankings. It does
not perform new embedding or SQL retrieval. This isolates the model and avoids
changing evidence between candidates. The application still uses PostgreSQL
and pgvector for live retrieval; replay is an evaluation command only.

The runner verifies the report's predeclared SHA256, corpus/embedding collection
fingerprint, query IDs and exact text, split/date/retrieval configuration,
prompt/schema fingerprints, chunk content/dates/provenance, duplicate IDs and
rank order. The saved report is a trusted evaluation artifact; consistency checks
do not independently authenticate its SQL origin. It re-reads gold labels from CSV for scoring only after generation;
stored expected answers or labels never enter the prompt. Regression reports
record ranked chunk hashes, model lock hashes and timing for every case.

Reproduce after the normal optional LLM dependency installation:

```bash
uv run --no-sync python scripts/download_llm.py \
  --lock llm.candidate.lock.json --output .cache/llm-candidate
uv run --no-sync refundguard evaluate-selector \
  --llm-model .cache/llm-candidate/Qwen3-4B-Instruct-2507-Q4_K_M.gguf \
  --llm-lock llm.candidate.lock.json \
  --retrieval-report reports/explanation_v2/dev.json \
  --retrieval-sha256 "$(uv run --no-sync python -c 'import json; print(json.load(open("config/model_comparison.json"))["retrieval_report_sha256"]["reports/explanation_v2/dev.json"])')" \
  --split dev --output reports/model_comparison_v1/dev_reproduction.json
```

For original regression, use the original heldout retrieval report and its
corresponding declared hash plus `--split heldout`. For the supplementary
regression, also supply `--questions-file data/explanation_questions_v2.csv`
and `--splits-file data/explanation_splits_v2.json`. Use new output filenames
so archived evidence remains unchanged.

The original live `evaluate-answers` and policy/assessment API paths continue
to require SQL and the pinned dense embedding index. See MODEL_COMPARISON_RESULTS.md
for the actual development decision and regression outcomes. Older SQL/HTTP
verification evidence remains archived; this isolated comparison does not
claim a fresh database or endpoint execution run.
