"""Isolated local-model evaluation on hash-checked, previously measured retrieval.

Replay does not claim to perform new embedding/SQL retrieval or new blind testing.
Gold values are reloaded from the labeled CSV and used only after generation.
"""

import inspect
import json
from datetime import UTC, date, datetime
from time import perf_counter

from .corpus import json_hash, load_corpus, sha256
from .dataset import load_questions, load_splits
from .explanation import SYSTEM_PROMPT, ModelOutput, explain, generation_schema, prompt
from .explanation_evaluation import score_answers
from .store import make_manifest


def checked_replay(path, expected_sha256, chunks, questions, config, split):
    raw = path.read_bytes()
    if sha256(raw) != expected_sha256:
        raise ValueError("Retrieval report does not match its declared hash")
    report = json.loads(raw)
    if report["split"] != split or report["status"] != "measured":
        raise ValueError("Wrong retrieval report split or status")
    if report["as_of"] != config["as_of_for_evaluation"]:
        raise ValueError("Replay assessment date differs from the frozen protocol")
    if report["protocol"]["retrieval"] != config["retrieval"]:
        raise ValueError("Replay retrieval configuration differs from the frozen protocol")
    if json_hash(make_manifest(chunks, report["embedding"])) != report["collection_id"]:
        raise ValueError("Replay collection does not match the local policy corpus")
    expected_hashes = {
        "prompt_sha256": sha256(SYSTEM_PROMPT.encode()),
        "prompt_template_sha256": sha256(inspect.getsource(prompt).encode()),
        "schema_sha256": json_hash(ModelOutput.model_json_schema()),
        "generation_schema_sha256": json_hash(generation_schema()),
    }
    if any(report["selector"].get(k) != v for k, v in expected_hashes.items()):
        raise ValueError("Replay explanation prompt/schema differs from the current protocol")
    cases = report["cases"]
    by_id = {c["id"]: c for c in cases}
    if len(by_id) != len(cases) or set(by_id) != {q.id for q in questions}:
        raise ValueError("Replay IDs do not match the selected question split")
    by_chunk = {c.chunk_id: c.to_dict() for c in chunks}
    for question in questions:
        case = by_id[question.id]
        if case["question"] != question.question:
            raise ValueError("Replay question text differs from the labeled dataset")
        hits = case["retrieved"]
        if len(hits) > config["retrieval"]["k"]:
            raise ValueError("Replay exceeds the declared top-k limit")
        if len({h["chunk_id"] for h in hits}) != len(hits):
            raise ValueError("Replay contains duplicate chunks")
        for rank, hit in enumerate(hits, 1):
            actual = by_chunk.get(hit["chunk_id"])
            if actual is None or hit["rank"] != rank:
                raise ValueError("Replay chunk ID or rank is invalid")
            # Normalize tuples to JSON lists without weakening text/date/hash checks.
            if any(json_hash(hit.get(k)) != json_hash(v) for k, v in actual.items()):
                raise ValueError("Replay evidence differs from the actual policy section")
    return report, by_id


def evaluate_selector(reference, by_id, questions, selector, config, split):
    if selector.spec["inference"] != reference["selector"]["inference"]:
        raise ValueError("This comparison requires unchanged inference settings")
    cases = []
    for question in questions:
        retrieved = by_id[question.id]["retrieved"]
        started = perf_counter()
        answer = explain(
            question.question,
            retrieved,
            selector,
            date.fromisoformat(config["as_of_for_evaluation"]),
        )
        elapsed = perf_counter() - started
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
                "inference_seconds": elapsed,
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
        "as_of": config["as_of_for_evaluation"],
        "collection_id": reference["collection_id"],
        "embedding": reference["embedding"],
        "selector": selector.spec,
        "protocol": config,
        "protocol_sha256": json_hash(config),
        "runtime": {
            "mode": "local CPU inference on replayed PostgreSQL/pgvector rankings",
            "new_embedding_or_sql_retrieval": False,
            "original_retrieval_runtime": reference["runtime"],
        },
        "metrics": score_answers(cases),
        "cases": cases,
        "not_measured": {"semantic_answer_correctness": None, "semantic_citation_entailment": None},
        "limitations": [
            "All labels and both heldout sets previously inspected; regression only.",
            "Replay isolates model selection; not a fresh SQL/embedding benchmark.",
            "Gold-label precision and quote support do not prove semantic correctness.",
            "Small synthetic dataset; no population-level accuracy claim.",
        ],
    }


def run_selector(args, write_json):
    from .explanation import LocalSelector

    config = json.loads(args.explanation_config.read_text())
    chunks = load_corpus(args.data_dir / "policies")
    question_path = args.questions_file or args.data_dir / "eval_questions.csv"
    split_path = args.splits_file or args.data_dir / "splits.json"
    questions = load_questions(question_path, chunks)
    splits = load_splits(split_path, questions)
    selected = [q for q in questions if q.id in splits[args.split]]
    reference, by_id = checked_replay(
        args.retrieval_report, args.retrieval_sha256, chunks, selected, config, args.split
    )
    selector = LocalSelector(args.llm_model, args.llm_lock)
    output = evaluate_selector(reference, by_id, selected, selector, config, args.split)
    output["replay"] = {
        "retrieval_report_sha256": args.retrieval_sha256,
        "ranked_chunk_ids_sha256": json_hash(
            {q.id: [h["chunk_id"] for h in by_id[q.id]["retrieved"]] for q in selected}
        ),
    }
    output["dataset"] = {
        "questions_sha256": sha256(question_path.read_bytes()),
        "splits_sha256": sha256(split_path.read_bytes()),
        "split_manifest": splits,
    }
    output["model_lock_sha256"] = sha256(args.llm_lock.read_bytes())
    write_json(args.output, output)
    print(json.dumps({"report": str(args.output), "metrics": output["metrics"]}, indent=2))
    return 0
