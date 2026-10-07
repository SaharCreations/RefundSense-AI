import numpy as np
import pytest

from refundguard.dataset import load_questions
from refundguard.embeddings import DIMENSIONS, validate_vectors
from refundguard.evaluation import evaluate


def test_retrieval_receives_only_query_embeddings_not_gold(data_dir, chunks):
    questions = load_questions(data_dir / "eval_questions.csv", chunks)[24:]
    calls = []

    class SpyEmbedder:
        spec = {"provider": "test-only"}

        def queries(self, texts):
            assert texts == [q.question for q in questions]
            return [[1.0] for _ in texts]

    class SpyStore:
        def retrieve(self, collection_id, vector, k, scope):
            calls.append((collection_id, vector, k, scope))
            return []

        def server_info(self):
            return {"test": True}

    report = evaluate(
        SpyStore(),
        SpyEmbedder(),
        "test",
        questions,
        chunks,
        [1, 5],
        "dev",
        data_dir / "eval_questions.csv",
        data_dir / "splits.json",
        "unit test",
    )
    assert len(calls) == 6 and all(c[-1] == "all" for c in calls)
    metrics = report["metrics"]
    assert metrics["unanswerable_evidence_only"]["recall_at_k"]["5"] == 0
    assert metrics["answerable"]["count"] == 0
    for name in ["citation_correctness", "abstention_accuracy", "rules_engine_accuracy"]:
        assert metrics[name]["value"] is None
        assert metrics[name]["status"] == "not_measured"


@pytest.mark.parametrize("value", [0.0, float("nan"), float("inf")])
def test_invalid_vectors_rejected(value):
    vectors = np.full((1, DIMENSIONS), value)
    with pytest.raises(ValueError):
        validate_vectors(vectors, 1)


def test_dimension_and_batch_count_checked():
    with pytest.raises(ValueError, match="dimension"):
        validate_vectors([[1.0, 2.0]], 1)
    with pytest.raises(ValueError, match="Expected"):
        validate_vectors(np.ones((1, DIMENSIONS)), 2)


def test_real_tokenizer_blocks_silent_truncation():
    # Exercise length validation with a tiny tokenizer; no model download for unit tests.
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    from refundguard.embeddings import DenseEmbedder

    model = DenseEmbedder.__new__(DenseEmbedder)
    model.tokenizer = Tokenizer(WordLevel({"[UNK]": 0, "word": 1}, unk_token="[UNK]"))
    model.tokenizer.pre_tokenizer = Whitespace()
    with pytest.raises(ValueError, match="silent truncation"):
        model._check_lengths(["word " * 513])
    with pytest.raises(ValueError, match="empty"):
        model._check_lengths([" "])
