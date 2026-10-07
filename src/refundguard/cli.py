"""Headless commands. Run from the project root or provide --data-dir."""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from .corpus import corpus_manifest, load_corpus
from .dataset import load_questions, load_splits


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement prevents a partially written report on interruption.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="RefundSense AI headless portfolio tools")
    root.add_argument("--data-dir", type=Path, default=Path("data"))
    root.add_argument(
        "--model-dir", type=Path, help="Optional predownloaded FastEmbed model folder"
    )
    root.add_argument("--rules-config", type=Path, default=Path("config/demo_ruleset.json"))
    sub = root.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Parse policies and validate all labels and splits")
    inspect.add_argument("--output", type=Path, default=Path("reports/corpus.json"))
    ingest = sub.add_parser("ingest", help="Embed policies and atomically store a corpus snapshot")
    ingest.add_argument("--output", type=Path, default=Path("reports/ingestion.json"))
    query = sub.add_parser(
        "query", help="Return ranked evidence; does not decide or execute refunds"
    )
    query.add_argument("question")
    query.add_argument("--k", type=int, default=5)
    query.add_argument("--scope", choices=["current", "all"], default="current")
    query.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    query.add_argument("--output", type=Path)
    evaluation = sub.add_parser("evaluate", help="Measure retrieval on the frozen query split")
    evaluation.add_argument("--split", choices=["dev", "heldout", "all"], default="dev")
    evaluation.add_argument("--k", type=int, nargs="+", default=[1, 3, 5])
    evaluation.add_argument("--output", type=Path)
    evaluation.add_argument(
        "--runtime-note", default="Runtime not supplied; inspect postgres_version."
    )
    sub.add_parser("seed-demo", help="Add synthetic SQL records without overwriting existing facts")
    assessment = sub.add_parser("assess", help="Assess exact SQL records; cannot execute a refund")
    assessment.add_argument(
        "--organization-id",
        required=True,
        help="Local demo scope; a future API must supply authenticated scope",
    )
    assessment.add_argument("--customer-id", required=True)
    assessment.add_argument("--order-id", required=True)
    assessment.add_argument("--requested-on", type=date.fromisoformat, default=date.today())
    assessment.add_argument("--reason", default="standard_return")
    assessment.add_argument("--refund-method", default="original_payment")
    assessment.add_argument("--include-shipping", action="store_true")
    assessment.add_argument("--include-tax", action="store_true")
    assessment.add_argument("--output", type=Path)
    rules_eval = sub.add_parser("evaluate-rules", help="Score labeled deterministic rule scenarios")
    rules_eval.add_argument("--split", choices=["dev", "heldout", "all"], default="dev")
    rules_eval.add_argument("--output", type=Path)
    rules_eval.add_argument("--report-directory", type=Path, default=Path("reports"))
    for command, help_text in [
        ("answer-policy", "Select and validate quoted policy evidence with the local LLM"),
        ("evaluate-answers", "Measure citation labels and abstention on the frozen split"),
    ]:
        answer = sub.add_parser(command, help=help_text)
        answer.add_argument("--llm-model", type=Path, required=True)
        answer.add_argument("--llm-lock", type=Path, default=Path("llm.lock.json"))
        answer.add_argument(
            "--explanation-config", type=Path, default=Path("config/explanation_baseline.json")
        )
        answer.add_argument("--output", type=Path)
        if command == "answer-policy":
            answer.add_argument("question")
            answer.add_argument("--as-of", type=date.fromisoformat, default=date.today())
        else:
            answer.add_argument("--split", choices=["dev", "heldout"], default="dev")
            answer.add_argument("--questions-file", type=Path)
            answer.add_argument("--splits-file", type=Path)
    replay = sub.add_parser(
        "evaluate-selector", help="Compare a local model on checked retrieval replay"
    )
    replay.add_argument("--llm-model", type=Path, required=True)
    replay.add_argument("--llm-lock", type=Path, required=True)
    replay.add_argument("--retrieval-report", type=Path, required=True)
    replay.add_argument("--retrieval-sha256", required=True)
    replay.add_argument(
        "--explanation-config", type=Path, default=Path("config/explanation_baseline.json")
    )
    replay.add_argument("--questions-file", type=Path)
    replay.add_argument("--splits-file", type=Path)
    replay.add_argument("--split", choices=["dev", "heldout"], default="dev")
    replay.add_argument("--output", type=Path, required=True)
    sub.add_parser("auth-init", help="Initialize SQL account and session schemas")
    user = sub.add_parser("auth-create-user", help="Provision an account through trusted local CLI")
    user.add_argument("--organization-id", required=True)
    user.add_argument("--user-id", required=True)
    user.add_argument("--role", choices=["support", "reviewer"], required=True)
    for command, help_text in [
        ("workflow-init", "Initialize PostgreSQL workflow and checkpoint schemas"),
        ("workflow-propose", "Pause with exact DEMO refund payload for human review"),
        ("workflow-view", "Show the immutable payload and current workflow status"),
        ("workflow-decide", "Record a human decision and execute only the approved DEMO payload"),
        ("workflow-recover", "Recover a persisted workflow after process failure"),
    ]:
        workflow = sub.add_parser(command, help=help_text)
        workflow.add_argument("--output", type=Path)
        if command == "workflow-init":
            continue
        workflow.add_argument("--organization-id", required=True, help="Local demo scope")
        workflow.add_argument("--user-id", required=True, help="Local demo reviewer identity")
        if command == "workflow-propose":
            workflow.add_argument("--order-id", required=True)
            workflow.add_argument("--customer-id", required=True)
            workflow.add_argument("--reason", default="standard_return")
        else:
            workflow.add_argument("--workflow-id", required=True)
        if command == "workflow-decide":
            workflow.add_argument("--decision", choices=["approve", "reject"], required=True)
            workflow.add_argument("--payload-sha256", required=True)
    return root


def run(args: argparse.Namespace) -> int:
    if args.command == "evaluate-selector":
        from .selector_evaluation import run_selector

        return run_selector(args, write_json)
    if args.command in {"answer-policy", "evaluate-answers"}:
        from .explanation_cli import run_explanation

        return run_explanation(args, write_json)
    if args.command.startswith("auth-"):
        from .auth_cli import run_auth

        return run_auth(args)
    if args.command.startswith("workflow-"):
        from .workflow_cli import run_workflow

        return run_workflow(args, write_json)
    if args.command in {"seed-demo", "assess", "evaluate-rules"}:
        from .assessment_cli import run_assessment

        return run_assessment(args, write_json)
    chunks = load_corpus(args.data_dir / "policies")
    if args.command in {"inspect", "evaluate"}:
        csv_path = args.data_dir / "eval_questions.csv"
        splits_path = args.data_dir / "splits.json"
        questions = load_questions(csv_path, chunks)
        splits = load_splits(splits_path, questions)
    if args.command == "inspect":
        output = {
            **corpus_manifest(chunks),
            "evaluation_questions": len(questions),
            "splits": {key: len(splits[key]) for key in ["dev", "heldout"]},
            "chunks_detail": [chunk.to_dict() for chunk in chunks],
        }
        write_json(args.output, output)
        print(json.dumps({k: v for k, v in output.items() if k != "chunks_detail"}, indent=2))
        return 0
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("Set DATABASE_URL to a PostgreSQL database with pgvector available.")
    if hasattr(args, "k"):
        ks = args.k if isinstance(args.k, list) else [args.k]
        if any(k < 1 or k > 1000 for k in ks):
            raise ValueError("Every k must be between 1 and 1000")
    from .embeddings import DenseEmbedder
    from .evaluation import evaluate
    from .store import PolicyStore, connection

    embedder = DenseEmbedder(model_dir=args.model_dir)
    if args.command == "ingest":
        # Complete expensive embedding before opening the write transaction.
        vectors = embedder.documents([chunk.embedding_text for chunk in chunks])
        with connection(database_url, initialize=True) as conn:
            store = PolicyStore(conn)
            collection_id = store.ingest(chunks, vectors, embedder.spec)
            output = {
                "status": "ingested",
                "collection_id": collection_id,
                **corpus_manifest(chunks),
                "embedding": embedder.spec,
                "runtime": store.server_info(),
            }
        write_json(args.output, output)
        print(
            json.dumps(
                {
                    "status": "ingested",
                    "chunks": len(chunks),
                    "collection_id": collection_id,
                    "report": str(args.output),
                },
                indent=2,
            )
        )
        return 0
    with connection(database_url) as conn:
        store = PolicyStore(conn)
        collection_id = store.require_collection(chunks, embedder.spec)
        if args.command == "query":
            vector = embedder.queries([args.question])[0]
            output = {
                "question": args.question,
                "scope": args.scope,
                "as_of": args.as_of.isoformat(),
                "collection_id": collection_id,
                "warning": "Retrieved evidence only. Historical text cannot authorize refunds.",
                "retrieved": store.retrieve(collection_id, vector, args.k, args.scope, args.as_of),
            }
            if args.output:
                write_json(args.output, output)
            print(json.dumps(output, indent=2, ensure_ascii=False))
        else:
            selected = (
                questions
                if args.split == "all"
                else [q for q in questions if q.id in splits[args.split]]
            )
            output = evaluate(
                store,
                embedder,
                collection_id,
                selected,
                chunks,
                args.k,
                args.split,
                csv_path,
                splits_path,
                args.runtime_note,
            )
            path = args.output or Path(f"reports/{args.split}.json")
            write_json(path, output)
            print(
                json.dumps(
                    {
                        "status": output["status"],
                        "split": args.split,
                        "metrics": output["metrics"],
                        "report": str(path),
                    },
                    indent=2,
                )
            )
    return 0


def main() -> int:
    args = parser().parse_args()
    try:
        return run(args)
    except (ValueError, FileNotFoundError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Do not print a connection URI or credentials in CLI error output.
        print(
            f"Operation failed ({type(exc).__name__}). Check database availability, "
            "pgvector installation, model download access, and write permissions.",
            file=sys.stderr,
        )
        return 1
