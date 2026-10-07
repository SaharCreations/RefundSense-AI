# Refund Assistant Seed Pack

This is the starting test environment for the portfolio project.

## Contents
- `policies/`: synthetic policy documents for RAG
- `eval_questions.csv`: 30 labeled evaluation questions

## Important design rules
- Policies are unstructured RAG content.
- Orders/customers will later live in relational PostgreSQL tables.
- The superseded policy is intentionally included to test version handling.
- Unanswerable questions are included to test abstention.
- Security questions test whether retrieved text is treated as untrusted data.

## Next implementation step
Build a headless Python ingestion + retrieval baseline:
1. parse Markdown
2. split by headings/sections
3. embed chunks
4. store in PostgreSQL + pgvector
5. retrieve top-k chunks for each eval question
6. calculate Recall@k / MRR against the expected section labels
