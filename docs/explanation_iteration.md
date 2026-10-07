# Conservative selection and abstention iteration

The dense collection, embedding model, chunks, source policies and original
30-question dataset remain unchanged. This iteration addresses the measured
selector failures: irrelevant quotations and answers to missing-policy questions.
No BM25, hybrid retrieval, reranking, services or architecture changes were added.

The same pinned Qwen2.5-1.5B-Instruct local CPU model is used. Changes are:

1. Put the actual question after evidence in the prompt; require direct support
   for both its subject and the requested fact.
2. Supply generic library-hours examples of supported and unsupported questions.
   They contain no refund policy facts or evaluation answers.
3. Prefer the minimum relevant quotations, rather than filling the citation array.
4. Enforce two JSON generation states: answer with 1–4 citations, or abstain with
   zero citations. A JSON `oneOf` grammar prevents contradictory combinations.
   Strict server validation remains independent and rejects contradictions,
   unrecognized fields, invented quotes, inactive policy clauses and bad references.
5. Record the complete prompt template and generation-schema fingerprints in
   addition to the original model, prompt and validation-schema fingerprints.

## Development sequence and freeze

The grammar-removal diagnostic replayed four development questions using the
same model and prompt. It did not fix irrelevant answers, and schema-invalid
outputs were still blocked. The diagnostic raw outputs are preserved.

Protocol v3 changed the prompt and question position. It improved gold-label
precision to 12/15 and unknown abstention to 3/4, but five outputs combined
abstention with quotations. These contradictions caused server abstentions,
including three of the four unknown questions. They were not silently accepted.

Protocol v4 adds mutually exclusive generation states and status-first output.
Development produced 11/11 gold-label citations, abstained on all four unknown
questions, and had no validator-blocked outputs. It also abstained on six of
16 answerable questions. This stricter protocol prioritizes refusing unsupported
answers and sacrifices coverage. It is an experimental conservative candidate,
not a claim of overall answer-quality improvement.

The final protocol was frozen after development and before running either the
supplementary heldout or the original heldout regression. No prompt, model,
retrieval or generation-schema changes followed their results. Exact source,
prompt, schemas, configuration and model fingerprints are preserved in reports.

## Evaluation datasets

The original development questions remain the tuning set. The original heldout
was already inspected in earlier milestones; its new results are explicitly
regression diagnostics, not fresh held-out validation.

The supplementary CSV combines the same 20 development questions with 12 new
synthetic held-out questions: eight answerable and four unanswerable, including
superseded-policy and injection cases. These were authored directly from the
policy by the implementer before final inference, and were excluded from tuning.
They are not blind, independently reviewed, representative customer data or a
statistically powered benchmark. Some overlap in policy concepts is unavoidable
with seven synthetic documents. Original data files are unchanged.

The CLI now permits explicit evaluation files without changing the policy corpus:

```bash
uv run --no-sync refundguard --model-dir .cache/model evaluate-answers \
  --llm-model .cache/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf \
  --questions-file data/explanation_questions_v2.csv \
  --splits-file data/explanation_splits_v2.json \
  --split heldout --output reports/explanation_v2/supplementary_heldout.json
```

Use the original files by omitting those two flags. With the current protocol,
treat original heldout runs as regression diagnostics. Do not overwrite archived
reports. `scripts/summarize_explanations.py` computes Recall@5, MRR@5 and emitted
label recall from actual saved retrieval/inference evidence; it does not rerank,
generate answers or tune. The comparison includes abstentions as zero emitted
label recall so higher precision cannot conceal lost coverage.

## Results and limits

See EXPLANATION_ITERATION_RESULTS.md. Exact quotation support and gold-label
precision still do not prove semantic completeness or customer-answer correctness.
Current results are too conservative for unattended customer responses. The
next model-quality experiment should use development-only selection and a
predeclared coverage criterion; previously observed heldout sets must stay
regression diagnostics. A genuinely independent heldout dataset needs another
reviewer or real anonymized cases and should not be claimed here.

FastAPI response shapes, authorization, SQL calculations, exact-ID requirements,
persistent human approvals, live revalidation, expiry, audit and idempotency
remain unchanged. Explanations cannot create approvals or ledger entries.
Assessment amounts and decisions come only from deterministic SQL/code paths.
