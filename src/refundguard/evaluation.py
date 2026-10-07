"""Evaluate measured database rankings; never ask an LLM to score retrieval."""

import platform
from datetime import UTC, datetime
from pathlib import Path

from .corpus import Chunk, corpus_manifest, sha256
from .dataset import Question
from .metrics import aggregate, recall_at_k, reciprocal_rank_at_k


def evaluate(
    store,
    embedder,
    collection_id: str,
    questions: list[Question],
    chunks: list[Chunk],
    ks: list[int],
    split_name: str,
    csv_path: Path,
    splits_path: Path,
    runtime_note: str,
) -> dict:
    ks = sorted(set(ks))
    if not ks or any(k < 1 or k > 1000 for k in ks):
        raise ValueError("Every k must be between 1 and 1000")
    # Only question text crosses the retrieval boundary, never labels or answers.
    vectors = embedder.queries([q.question for q in questions])
    rows = []
    for question, vector in zip(questions, vectors, strict=True):
        hits = store.retrieve(collection_id, vector, max(ks), scope="all")
        ranked = [(hit["source"], hit["section"]) for hit in hits]
        rows.append(
            {
                "id": question.id,
                "category": question.category,
                "question": question.question,
                "expected_behavior": question.expected_behavior,
                "expected_labels": [list(label) for label in sorted(question.expected)],
                "recall_at_k": {str(k): recall_at_k(question.expected, ranked, k) for k in ks},
                "reciprocal_rank_at_k": {
                    str(k): reciprocal_rank_at_k(question.expected, ranked, k) for k in ks
                },
                "missing_at_max_k": [
                    list(label) for label in sorted(question.expected - set(ranked))
                ],
                "retrieved": hits,
            }
        )
    answerable = [r for r in rows if r["expected_behavior"] == "answer"]
    unanswerable = [r for r in rows if r["expected_behavior"] == "abstain"]
    return {
        "status": "measured",
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "split": split_name,
        "configuration": {
            "k": ks,
            "scope": "all",
            "ranking": "pgvector exact cosine distance",
            "tie_break": ["source", "section", "chunk_id"],
            "collection_id": collection_id,
            "embedding": embedder.spec,
            "corpus": corpus_manifest(chunks),
            "eval_csv_sha256": sha256(csv_path.read_bytes()),
            "splits_sha256": sha256(splits_path.read_bytes()),
        },
        "runtime": {
            "python": platform.python_version(),
            **store.server_info(),
            "note": runtime_note,
        },
        "definitions": {
            "recall_at_k": (
                "Per query: distinct relevant (source, section) labels in top k / all gold labels; "
                "then macro mean."
            ),
            "mrr_at_k": (
                "Mean of 1 / first relevant rank within top k; zero if absent. "
                "This is truncated MRR@k, not unbounded MRR."
            ),
            "multi_section": (
                "All listed sections count toward Recall; "
                "MRR rewards the first relevant section only."
            ),
            "all_labeled_diagnostic": (
                "Includes abstain questions whose gold labels identify escalation evidence; "
                "this is not answer or abstention accuracy."
            ),
        },
        "metrics": {
            "answerable": aggregate(answerable, ks),
            "unanswerable_evidence_only": aggregate(unanswerable, ks),
            "all_labeled_diagnostic": aggregate(rows, ks),
            "by_category": {
                category: aggregate(
                    [r for r in rows if r["category"] == category],
                    ks,
                )
                for category in sorted({r["category"] for r in rows})
            },
            "citation_correctness": {
                "value": None,
                "status": "not_measured",
                "reason": "No answer generator exists in this baseline.",
            },
            "abstention_accuracy": {
                "value": None,
                "status": "not_measured",
                "reason": "No answerability classifier or calibrated threshold exists.",
            },
            "rules_engine_accuracy": {
                "value": None,
                "status": "not_measured",
                "reason": "Refund rules engine is a later milestone.",
            },
        },
        "questions": rows,
    }
