"""Headless extractive policy answers and measured answer/abstention behavior."""

import json
import os
from datetime import date
from pathlib import Path

from .corpus import load_corpus, sha256
from .dataset import load_questions, load_splits
from .embeddings import DenseEmbedder
from .explanation import LocalSelector, explain
from .explanation_evaluation import evaluate_answers
from .store import PolicyStore, connection


def run_explanation(args, write_json):
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("Set DATABASE_URL")
    if args.model_dir is None or args.llm_model is None:
        raise ValueError("Provide --model-dir and --llm-model for explicit pinned local artifacts")
    config = json.loads(args.explanation_config.read_text())
    chunks = load_corpus(args.data_dir / "policies")
    embedder = DenseEmbedder(args.model_dir)
    selector = LocalSelector(args.llm_model, args.llm_lock)
    with connection(url) as conn:
        store = PolicyStore(conn)
        collection_id = store.require_collection(chunks, embedder.spec)
        if args.command == "answer-policy":
            vector = embedder.queries([args.question])[0]
            as_of = args.as_of
            retrieved = store.retrieve(
                collection_id,
                vector,
                config["retrieval"]["k"],
                config["retrieval"]["policy_api_scope"],
                as_of,
            )
            output = {
                "question": args.question,
                "as_of": as_of.isoformat(),
                "collection_id": collection_id,
                "answer": explain(args.question, retrieved, selector, as_of),
                "selector": selector.spec,
                "retrieved": retrieved,
            }
            if args.output:
                write_json(args.output, output)
            print(json.dumps(output, indent=2))
        else:
            questions_path = args.questions_file or args.data_dir / "eval_questions.csv"
            splits_path = args.splits_file or args.data_dir / "splits.json"
            questions = load_questions(questions_path, chunks)
            splits = load_splits(splits_path, questions)
            selected = [q for q in questions if q.id in splits[args.split]]
            output = evaluate_answers(
                store,
                embedder,
                collection_id,
                selected,
                selector,
                date.fromisoformat(config["as_of_for_evaluation"]),
                config,
                args.split,
            )
            output["dataset"] = {
                "questions_sha256": sha256(questions_path.read_bytes()),
                "splits_sha256": sha256(splits_path.read_bytes()),
                "split_manifest": splits,
            }
            path = args.output or Path(f"reports/answers_{args.split}.json")
            write_json(path, output)
            print(
                json.dumps(
                    {"split": args.split, "metrics": output["metrics"], "report": str(path)},
                    indent=2,
                )
            )
    return 0
