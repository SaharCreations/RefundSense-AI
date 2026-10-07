# Extractive explanation baseline

The current default prompt/generation protocol is v4, the conservative experiment
described in [explanation_iteration.md](explanation_iteration.md). The original
v2 baseline reports remain archived. Use the new supplementary CLI flags for
the current heldout experiment; original heldout runs are regression diagnostics.

The optional local LLM selects exact policy quotations. Server code validates
its strict schema, evidence IDs, quotation support, policy dates and status.
The response contains server-owned source hashes and section/line provenance.
The model cannot return money, order/customer IDs, decisions, arbitrary prose,
SQL, tool calls or execution payloads. No explanation creates an approval or
executes a refund. SQL rules remain authoritative; deterministic code renders
amounts and decisions in assessment explanations.

This is an extractive first baseline, not a free-form chatbot. Exact quotation
support does not prove relevance, completeness or semantic correctness. A
validated quote can still answer the wrong question. Missing/invalid evidence
or model output produces an abstention requiring human review.

## Installation and reproduction

Python 3.12+, uv, a C/C++ compiler and CMake are needed for the optional native
llama.cpp Python build. Install with `uv sync --locked --extra dev --extra llm`.
On a CPU-only Linux environment with GCC, an explicit build can use:

```bash
CC=gcc CXX=g++ CMAKE_BUILD_PARALLEL_LEVEL=2 \
CMAKE_ARGS='-DGGML_NATIVE=OFF -DGGML_BLAS=OFF' \
uv sync --locked --extra dev --extra llm
uv run --no-sync python scripts/download_llm.py
```

The explicit download verifies the commit, file size and SHA256 in
`llm.lock.json`: official Qwen2.5-1.5B-Instruct, Q4_K_M GGUF, approximately 1.1 GB.
The model has an Apache 2.0 license. Weights are excluded from the project ZIP.
Inference is local CPU, two threads, 4096-token context, temperature zero,
seed 17. No paid API key or extra model service is used. Hash verification
happens before loading. API requests never download models.

First ingest the pinned dense embedding collection using the README commands.
Then run from the project directory with DATABASE_URL set:

```bash
export ORT_DISABLE_TELEMETRY=1
uv run --no-sync refundguard --model-dir .cache/model answer-policy \
  'What is the current opened electronics restocking fee?' \
  --llm-model .cache/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf \
  --as-of 2026-10-06
uv run --no-sync refundguard --model-dir .cache/model evaluate-answers \
  --llm-model .cache/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf \
  --split dev --output reports/explanation_v2/dev_reproduction.json
uv run --no-sync refundguard --model-dir .cache/model evaluate-answers \
  --llm-model .cache/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf \
  --split heldout --output reports/explanation_v2/original_heldout_reproduction.json
```

Keep `--extra llm` when syncing, or use `--no-sync` for commands after installation
so uv does not remove the optional runtime. The package sets ONNX Runtime's
`ORT_DISABLE_TELEMETRY=1` before importing it; an already initialized unsafe
runtime requires a process restart. This documented opt-out was verified with
an embedding smoke test and import-boundary regression tests. Network tracing
was unavailable; no comprehensive egress-trace claim is made.

## API contract

Set REFUNDGUARD_MODEL_DIR, REFUNDGUARD_LLM_MODEL and optionally
REFUNDGUARD_LLM_LOCK before launching the existing authenticated FastAPI factory.
Existing SQL bearer authentication and organization scope apply.

- `POST /api/v1/policy/answer`: body `{ "question": "...", "k": 5 }`.
  Returns an answer/abstention and model provenance. Historical search candidates
  are allowed only for explicit superseded-status metadata quotations. Historical
  windows, fees and eligibility are rejected by code.
- `POST /api/v1/assessments/explain`: the same exact order/customer IDs and reason
  accepted by `/assessments`. Returns authoritative SQL assessment, code-written
  summary and separately guarded policy quotations. Dense current-policy top-5
  retrieval is restricted to the assessment's allowed citation labels; missed
  labels are never inserted. No amounts, record IDs or payment references enter
  the LLM prompt.

Raw model output is retained in offline evaluation reports, not API responses.
`execution_allowed` is always false. A successful explanation is not approval.
Policy explanations cover the synthetic ORG-DEMO policy bundle only.

## Evaluation protocol

Dense retrieval, chunks, embeddings and original 20/10 split remain unchanged.
Only question text and actual retrieved evidence reach the model. Expected
labels and answers are used after inference to score reports. The protocol is
`config/explanation_baseline.json`; reports capture model, prompt, schema,
corpus/embedding and protocol fingerprints plus raw outputs and per-case evidence.

The first development attempt used an abstain-first boolean schema and produced
20 abstentions, including 16 answerable questions. Four outputs also contradicted
their abstention flag. This failure is preserved in `dev_attempt_1.json` with
its exact protocol source and configuration. Version 2 changes the output to
citations-first with an explicit answer/abstain enum and generic library-hours
format examples. This tuning used development outcomes only. Version 2 is frozen
before the explanation held-out run. The original labels and prior retrieval
held-out results were already inspected, so this is not a new blind benchmark.

Citation correctness means gold-label precision: emitted source/section labels
in the expected set divided by all emitted citations. It is not semantic
entailment. Verbatim support is conditional on accepted quotes. Abstention
accuracy counts final answer/abstain behavior, including validator-blocked
outputs as abstentions. Answerable coverage and unknown abstention rate are
reported separately so refusing every question cannot appear successful.
No semantic answer or citation-entailment metric is invented.

Measured results and remaining failures are in `EXPLANATION_RESULTS.md`.
Native PostgreSQL rollback, trigger and concurrency gates from earlier milestones
remain pending. The temporary PGlite verification harness is not an application
dependency. Next priority: improve measured relevance and abstention before customer-facing
AI explanations. The planned frontend remains Next.js + TypeScript.

## Larger-model experiment

The model comparison retained the current 1.5B default because the 4B candidate
failed its predeclared development coverage requirement. See
[model_comparison.md](model_comparison.md) for replay validation, commands and
regression-only interpretation. Live retrieval and API setup remain unchanged.
