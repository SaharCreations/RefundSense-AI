"""Derive retrieval/selection diagnostics from saved actual inference evidence.

No inference, tuning or data mutation. Includes abstentions in citation coverage;
compares only original development questions across iterations.
"""

import argparse
import json
from pathlib import Path

from refundguard.metrics import recall_at_k, reciprocal_rank_at_k


def summarize(report):
    answerable = [c for c in report["cases"] if c["expected_behavior"] == "answer"]
    unknown = [c for c in report["cases"] if c["expected_behavior"] == "abstain"]
    rows = []
    for case in answerable:
        expected = {tuple(label) for label in case["expected_labels"]}
        ranked = [(c["source"], c["section"]) for c in case["retrieved"]]
        cited = {(c["source"], c["section"]) for c in case["answer"]["citations"]}
        rows.append(
            {
                "id": case["id"],
                "retrieval_recall_at_5": recall_at_k(expected, ranked, 5),
                "retrieval_reciprocal_rank_at_5": reciprocal_rank_at_k(expected, ranked, 5),
                "emitted_gold_label_recall": len(expected & cited) / len(expected),
                "gold_evidence_in_top5": bool(expected & set(ranked[:5])),
                "status": case["answer"]["status"],
                "abstention_reason": case["answer"]["abstention_reason"],
            }
        )
    return {
        "split": report["split"],
        "questions": report["questions"],
        "selector_fingerprint": report["selector"]["fingerprint"],
        "metrics": report["metrics"],
        "answerable_retrieval_recall_at_5": (
            sum(r["retrieval_recall_at_5"] for r in rows) / len(rows) if rows else None
        ),
        "answerable_retrieval_mrr_at_5": (
            sum(r["retrieval_reciprocal_rank_at_5"] for r in rows) / len(rows) if rows else None
        ),
        "answerable_emitted_gold_label_recall": (
            sum(r["emitted_gold_label_recall"] for r in rows) / len(rows) if rows else None
        ),
        "answerable_abstentions_with_gold_evidence_in_top5": [
            r["id"] for r in rows if r["status"] == "abstain" and r["gold_evidence_in_top5"]
        ],
        "unknown_model_abstentions": sum(
            c["answer"]["abstention_reason"] == "model_abstained" for c in unknown
        ),
        "unknown_validator_abstentions": sum(
            c["answer"]["status"] == "abstain"
            and c["answer"]["abstention_reason"]
            not in {"model_abstained", "no_eligible_retrieved_evidence"}
            for c in unknown
        ),
        "answerable_rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = [json.loads(p.read_text()) for p in args.reports]
    summaries = {str(p): summarize(r) for p, r in zip(args.reports, reports, strict=True)}
    original_dev = [
        r
        for r in reports
        if r["split"] == "dev"
        and {c["id"] for c in r["cases"]} == {c["id"] for c in reports[0]["cases"]}
    ]
    same_retrieval = (
        all(
            {c["id"]: [h["chunk_id"] for h in c["retrieved"]] for c in r["cases"]}
            == {c["id"]: [h["chunk_id"] for h in c["retrieved"]] for c in original_dev[0]["cases"]}
            for r in original_dev
        )
        if original_dev
        else None
    )
    args.output.write_text(
        json.dumps(
            {
                "development_ranked_chunk_ids_unchanged": same_retrieval,
                "definitions": {
                    "retrieval": "Macro Recall@5 and MRR@5 across answerable questions only.",
                    "emitted_gold_label_recall": (
                        "Macro fraction of gold labels emitted across ALL answerable questions; "
                        "abstentions contribute zero. Labels are not semantic entailment."
                    ),
                    "comparison": (
                        "Development tuning comparison only. Supplementary heldout differs from "
                        "original heldout; do not compare percentages as a same-set improvement."
                    ),
                },
                "reports": summaries,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
