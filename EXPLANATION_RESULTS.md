# Explanation baseline results

Real CPU inference used the pinned Qwen2.5-1.5B-Instruct Q4_K_M model,
llama-cpp-python 0.3.36 and the existing dense top-5 pgvector collection.
The frozen second protocol was measured on 20 development and 10 held-out
questions. No retrieval, gold-label injection or calculation changes were made.

| Metric | Development | Held-out |
| --- | --- | --- |
| Gold-label citation precision | 14/49 (28.6%) | 7/22 (31.8%) |
| Accepted quotes supported verbatim | 49/49 (100.0%) | 22/22 (100.0%) |
| Answer/abstain behavior accuracy | 15/20 (75.0%) | 8/10 (80.0%) |
| Answerable coverage | 15/16 (93.8%) | 8/8 (100.0%) |
| Unanswerable abstention rate | 0/4 (0.0%) | 0/2 (0.0%) |

**This model is not ready for unattended customer answers.** It answered both
held-out unanswerable questions and all four development unanswerable questions
with authentic but irrelevant policy quotations. Behavior accuracy of 80% on
held-out is driven by the eight answerable questions, not successful abstention.
100% quote support is enforced by validation and is conditional on accepted
quotes; it does not prove semantic correctness or policy relevance.

Gold-label citation precision is only 7/22 on held-out. Multiple extraneous
citations reduce precision; some relevant expected sections are absent from the
retrieved top-5 set. Server validation catches invented quotation text,
unsupported evidence IDs and inactive policy use, but cannot prove that a
quotation answers the question. No semantic entailment or full answer accuracy
metric was measured. Inspect every case in the raw reports before interpreting
these numbers.

The first attempt is preserved as `dev_attempt_1.json`: 20 abstentions, including
16 answerable questions, and four contradictory model outputs. Development-only
tuning changed the schema to citations-first with answer/abstain status and
simplified generic format examples. The final held-out model/protocol
fingerprints exactly match development. No changes followed held-out results.
The original labels and prior retrieval held-out results were already inspected;
this is a small synthetic partition, not a new blind benchmark.

The original dense retrieval metrics remain unchanged in BASELINE_RESULTS.md.
Deterministic rule evaluations and approval/API evidence remain archived. The
explanation layer cannot decide eligibility, compute money, grant approval or
execute refunds. SQL amounts are rendered by code in the separate assessment
summary. No real payment provider is connected.

Next evaluation priority: improve relevance selection and unknown-question
abstention on development data, using a stronger local model or a separately
evaluated answerability stage. Create a new held-out set before claiming a
fresh unbiased comparison. This failure does not justify adding BM25 or a
reranker without a retrieval-specific experiment. The planned frontend remains
Next.js + TypeScript, FastAPI and PostgreSQL + pgvector.

See docs/explanations.md for installation, commands and validation limits.
Raw reports under reports/explanation_v1 contain all retrieved evidence, model
outputs, denominator counts, protocol and model fingerprints.

Verification: 154 tests passed, 7 native-only checks skipped; 21 real HTTP checks
passed through two Uvicorn processes. Actual local LLM routes preserve the SQL
assessment and do not create ledger entries. The subsequent exact-payload human
approval executed one synthetic ledger refund; repeat/recovery created no duplicate.
