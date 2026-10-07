"""Frozen question split; gold data is used only AFTER retrieval and generation."""

from datetime import UTC, datetime

from .corpus import json_hash
from .explanation import explain, normalized


def fraction(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def score_answers(cases):
    citations = [(case, citation) for case in cases for citation in case["answer"]["citations"]]
    correct_citations = sum(
        (c["source"], c["section"]) in {tuple(label) for label in case["expected_labels"]}
        for case, c in citations
    )
    supported = sum(
        normalized(c["quote"])
        in normalized(
            next(chunk["text"] for chunk in case["retrieved"] if chunk["chunk_id"] == c["chunk_id"])
        )
        for case, c in citations
    )
    correct_behavior = sum(
        ("abstain" if c["answer"]["status"] == "abstain" else "answer") == c["expected_behavior"]
        for c in cases
    )
    answerable = [c for c in cases if c["expected_behavior"] == "answer"]
    unknown = [c for c in cases if c["expected_behavior"] == "abstain"]
    answered = sum(c["answer"]["status"] == "answered" for c in answerable)
    true_abstentions = sum(c["answer"]["status"] == "abstain" for c in unknown)
    return {
        "citation_correctness": fraction(correct_citations, len(citations)),
        "citation_verbatim_support": fraction(supported, len(citations)),
        "abstention_accuracy": fraction(correct_behavior, len(cases)),
        "answerable_coverage": fraction(answered, len(answerable)),
        "unanswerable_abstention_rate": fraction(true_abstentions, len(unknown)),
        "behavior_counts": {
            "answerable_answered": answered,
            "answerable_abstained": len(answerable) - answered,
            "unanswerable_abstained": true_abstentions,
            "unanswerable_answered": len(unknown) - true_abstentions,
        },
        "model_outputs_blocked": sum(
            c["answer"]["status"] == "abstain"
            and c["answer"]["abstention_reason"]
            not in {"model_abstained", "no_eligible_retrieved_evidence"}
            for c in cases
        ),
    }


def evaluate_answers(store, embedder, collection_id, questions, selector, as_of, config, split):
    vectors = embedder.queries([q.question for q in questions])
    cases = []
    for question, vector in zip(questions, vectors, strict=True):
        retrieved = store.retrieve(
            collection_id,
            vector,
            config["retrieval"]["k"],
            config["retrieval"]["evaluation_scope"],
            as_of,
        )
        # Only question text and actual top-k evidence enter inference, never gold labels.
        answer = explain(question.question, retrieved, selector, as_of)
        cases.append(
            {
                "id": question.id,
                "category": question.category,
                "question": question.question,
                "expected_behavior": question.expected_behavior,
                "expected_labels": sorted(question.expected),
                "expected_answer": question.expected_answer,
                "retrieved": retrieved,
                "answer": answer,
            }
        )
        print(
            f"{question.id}: {answer['status']} "
            f"({answer['abstention_reason'] or 'validated quotes'})",
            flush=True,
        )
    return {
        "status": "measured",
        "split": split,
        "questions": len(questions),
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": as_of.isoformat(),
        "collection_id": collection_id,
        "embedding": embedder.spec,
        "selector": selector.spec,
        "protocol": config,
        "protocol_sha256": json_hash(config),
        "runtime": store.server_info(),
        "metrics": score_answers(cases),
        "cases": cases,
        "not_measured": {"semantic_answer_correctness": None, "semantic_citation_entailment": None},
        "limitations": [
            "Small synthetic set; original labels and prior retrieval heldout inspected.",
            "Gold-label citation precision is a relevance proxy, not semantic entailment.",
            "Support precision is conditional on emitted, validated quotes.",
            "Failures/invalid generations count as abstention; coverage reported separately.",
            "Temperature zero and fixed seed do not guarantee cross-platform identical outputs.",
        ],
    }
