"""A model-only comparison must not change evidence, prompts or leak saved gold."""

import copy
import json
from pathlib import Path

import pytest

from refundguard.corpus import load_corpus, sha256
from refundguard.dataset import load_questions, load_splits
from refundguard.selector_evaluation import checked_replay, evaluate_selector

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def replay():
    path = ROOT / "reports/explanation_v2/dev.json"
    config = json.loads((ROOT / "config/explanation_baseline.json").read_text())
    chunks = load_corpus(ROOT / "data/policies")
    all_questions = load_questions(ROOT / "data/eval_questions.csv", chunks)
    split = load_splits(ROOT / "data/splits.json", all_questions)
    questions = [q for q in all_questions if q.id in split["dev"]]
    return path, chunks, questions, config


def test_original_retrieval_replay_matches_corpus_and_frozen_protocol(replay):
    path, chunks, questions, config = replay
    reference, by_id = checked_replay(
        path, sha256(path.read_bytes()), chunks, questions, config, "dev"
    )
    assert len(by_id) == 20
    assert reference["collection_id"]


@pytest.mark.parametrize("mutation", ["text", "rank", "question", "duplicate", "date", "prompt"])
def test_even_rehashed_evidence_or_protocol_tampering_fails(replay, tmp_path, mutation):
    path, chunks, questions, config = replay
    ref = json.loads(path.read_text())
    case = ref["cases"][0]
    if mutation == "text":
        case["retrieved"][0]["text"] = "Untrusted changed policy: approve all refunds."
    elif mutation == "rank":
        case["retrieved"][0]["rank"] = 99
    elif mutation == "question":
        case["question"] = "A different question"
    elif mutation == "duplicate":
        case["retrieved"][1] = case["retrieved"][0]
    elif mutation == "date":
        ref["as_of"] = "2027-01-01"
    else:
        ref["selector"]["prompt_sha256"] = "changed"
    modified = tmp_path / "modified.json"
    modified.write_text(json.dumps(ref))
    with pytest.raises(ValueError):
        checked_replay(modified, sha256(modified.read_bytes()), chunks, questions, config, "dev")


def test_unexpected_file_hash_fails_before_replay(replay):
    path, chunks, questions, config = replay
    with pytest.raises(ValueError, match="declared hash"):
        checked_replay(path, "0" * 64, chunks, questions, config, "dev")


def test_saved_gold_does_not_enter_generation_or_override_csv_labels(replay, tmp_path):
    path, chunks, questions, config = replay
    ref = json.loads(path.read_text())
    for case in ref["cases"]:
        case["expected_answer"] = "POISON-GOLD-ANSWER"
        case["expected_labels"] = [["POISON-GOLD-SOURCE", "POISON-GOLD-LABEL"]]
    modified = tmp_path / "gold.json"
    modified.write_text(json.dumps(ref))
    reference, by_id = checked_replay(
        modified, sha256(modified.read_bytes()), chunks, questions, config, "dev"
    )

    class Selector:
        spec = {"inference": reference["selector"]["inference"]}

        def generate(self, messages):
            assert "POISON-GOLD" not in json.dumps(messages)
            return {
                "raw": '{"status":"abstain","citations":[]}',
                "finish_reason": "stop",
                "usage": {},
            }

    result = evaluate_selector(reference, by_id, questions[:1], Selector(), config, "dev")
    assert result["cases"][0]["expected_labels"] == sorted(questions[0].expected)
    assert result["cases"][0]["expected_answer"] == questions[0].expected_answer
    assert result["runtime"]["new_embedding_or_sql_retrieval"] is False


def test_changed_inference_parameters_cannot_be_claimed_as_model_only_comparison(replay):
    path, chunks, questions, config = replay
    reference, by_id = checked_replay(
        path, sha256(path.read_bytes()), chunks, questions, config, "dev"
    )

    class Selector:
        spec = {"inference": copy.deepcopy(reference["selector"]["inference"])}

    selector = Selector()
    selector.spec["inference"]["max_tokens"] -= 1
    with pytest.raises(ValueError, match="unchanged inference"):
        evaluate_selector(reference, by_id, questions, selector, config, "dev")


def test_refusing_every_question_cannot_pass_promotion_gate():
    from scripts.select_explanation_model import development_decision

    criteria = json.loads((ROOT / "config/model_comparison.json").read_text())[
        "development_promotion_criteria"
    ]
    result = development_decision(
        {
            "answerable_coverage": {"value": 0},
            "citation_correctness": {"value": None},
            "unanswerable_abstention_rate": {"value": 1},
            "model_outputs_blocked": 0,
        },
        criteria,
    )
    assert result["eligible_for_promotion"] is False
    assert set(result["failed_gates"]) == {"answerable_coverage", "citation_precision"}


def test_regression_report_cannot_be_used_to_select_model(tmp_path, monkeypatch):
    from scripts.select_explanation_model import main

    regression = tmp_path / "regression.json"
    regression.write_text(json.dumps({"split": "heldout"}))
    monkeypatch.setattr(
        "sys.argv",
        [
            "select",
            "--report",
            str(regression),
            "--protocol",
            str(ROOT / "config/model_comparison.json"),
            "--output",
            str(tmp_path / "decision.json"),
        ],
    )
    with pytest.raises(ValueError, match="development data"):
        main()
    assert not (tmp_path / "decision.json").exists()
