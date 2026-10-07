# Frozen baseline protocol

This configuration was chosen before inspecting retrieval scores.

- Data: the supplied 7 Markdown policies and 30 labeled CSV questions, unchanged.
- Chunks: one per labeled heading, plus a document-status chunk for each policy.
  A heading's direct body ends at the next heading; nested headings retain their path.
- Embedded text: document title, version, status, dates, heading path, and body.
- Embeddings: `BAAI/bge-small-en-v1.5`, FastEmbed 0.8.1, 384 dimensions, CPU,
  normalized vectors. Record hashes of the actual model artifacts in every run.
- Database: PostgreSQL with pgvector, exact cosine distance; no approximate index.
- Ranking ties: source filename, section label, chunk ID.
- Evaluation search scope: **all policies**, including superseded documents.
  Apply the same scope to every question; gold labels never filter retrieval.
- k values: 1, 3, 5. Report macro section-level Recall@k and MRR@k.
- Split: the fixed 20 dev / 10 held-out IDs in `data/splits.json`. Related question
  groups Q02/Q13, Q11/Q23, and Q20/Q24 stay within one split.
- Gold semantics: all listed sections count toward recall, including when two
  sections repeat the same rule. Multiple sources/sections are paired in order;
  one source with several sections expands within that source. Missing or
  ambiguous labels fail validation.
- Do not use expected answers to build embeddings or choose rankings.
- Separate answerable retrieval scores from unanswerable evidence retrieval.
  Retrieving RP-7 is not a prediction to abstain.
- Citation correctness, abstention accuracy, and deterministic-rule accuracy are
  unmeasured in this milestone, represented by null values and an explanation.
- Do not add BM25, hybrid search, reranking, boosts, or model changes during this run.

The questions and labels were inspected to validate their format. This is a small
synthetic held-out query split, not a blind benchmark or a held-out policy split.
Both splits intentionally use the same policy corpus. If later improvements are
chosen based on held-out outcomes, add fresh held-out questions for a valid next
comparison. Do not change the seed labels to improve scores.

Current-only CLI queries exclude superseded documents and documents whose
effective date is after `--as-of`. That filter is not a historical policy selector
and does not establish the policy governing any particular order. Order-specific
policy applicability belongs in the later deterministic application layer.
