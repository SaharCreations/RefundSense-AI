# Larger local model comparison results

**The 4B candidate is not promoted.** It failed the coverage requirement
predeclared before generation. The default remains Qwen2.5-1.5B-Instruct with
the conservative v4 protocol. No threshold or prompt was changed after scoring.

| Split | Model | Answerable coverage | Gold-label citation precision | Unknown abstention | Answer/abstain behavior accuracy |
| --- | --- | --- | --- | --- | --- |
| Original development | 1.5B current | 10/16 (62.5%) | 11/11 (100.0%) | 4/4 (100.0%) | 14/20 (70.0%) |
| Original development | 4B candidate | 8/16 (50.0%) | 8/8 (100.0%) | 4/4 (100.0%) | 12/20 (60.0%) |
| Supplementary regression | 1.5B current | 4/8 (50.0%) | 4/4 (100.0%) | 4/4 (100.0%) | 8/12 (66.7%) |
| Supplementary regression | 4B candidate | 6/8 (75.0%) | 6/6 (100.0%) | 4/4 (100.0%) | 10/12 (83.3%) |
| Original heldout regression | 1.5B current | 2/8 (25.0%) | 2/2 (100.0%) | 2/2 (100.0%) | 4/10 (40.0%) |
| Original heldout regression | 4B candidate | 4/8 (50.0%) | 4/4 (100.0%) | 2/2 (100.0%) | 6/10 (60.0%) |

The development gate required at least 13/16 answerable questions answered,
at least 90% gold-label precision, all four unknown questions refused and no
validator-blocked model outputs. The candidate answered only 8/16, versus
10/16 for the current model. It passed the other three gates.
`development_decision.json` was written before regression inference.

Regression coverage improved on both previously observed sets, but those
outcomes cannot override a selection rule based on development. Both sets had
already been inspected, and the supplementary questions were authored by the
implementer. These are regression comparisons, not new blind validation.

All accepted quotes in the three candidate runs were verbatim supported and
gold-label relevant; there were no blocked outputs. Precision over 8, 6 and 4
quotes does not prove semantic completeness, entailment or broad accuracy. The
model still refuses supported questions. No semantic answer-quality metric is
invented. Changing the model alone did not consistently improve useful-answer
coverage under this prompt and schema.

Actual local inference used the pinned 2.5 GB Unsloth Q4_K_M GGUF of Qwen3-4B
Instruct-2507. This changes model family/version as well as size, so results
cannot be attributed solely to parameter count. The GGUF is a third-party
quantization. The recorded upstream base revision is an observation, not proof
of the exact commit used to create the quantized artifact.

The same saved PostgreSQL/pgvector rankings were replayed after checking
predeclared report hashes, collection/corpus fingerprints, queries, ranks,
policy content and prompt/schema identity. There was no new SQL or embedding
run. Answerable retrieval Recall@5/MRR@5 remain 0.8125/0.677083 on development,
0.875/0.75 on supplementary and 0.75/0.572917 on original heldout regression.
Detailed emitted label recall and missed evidence are in the diagnostics JSON.

100 non-integration tests passed, including replay tampering, gold-leakage,
inference-setting consistency, all-abstention rejection and prevention of model
selection from regression reports. SQL/HTTP tests were not rerun for this
isolated model-only experiment. Prior SQL-backed verification and native
PostgreSQL rollback/trigger/concurrency gates remain archived and pending.

The default model lock, explanation source/configuration, original policies
and question split, deterministic calculations, auth, API routes and approval
workflow remain unchanged. No paid API, new service or retrieval technique was
added. No refund action was performed by this experiment.

Next project milestone: Next.js + TypeScript review dashboard over the existing
FastAPI endpoints. Keep AI explanations visibly experimental, show abstentions
and policy evidence, and display the exact server-generated execution payload
for human approval. This experiment does not make customer-facing AI answers
production-ready.
