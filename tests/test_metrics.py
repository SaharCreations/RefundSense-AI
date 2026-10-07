import pytest

from refundguard.metrics import aggregate, recall_at_k, reciprocal_rank_at_k

A, B, X = ("a.md", "RP-1"), ("b.md", "PC-2"), ("x.md", "RP-1")


def test_hand_calculated_multisection_recall_and_rr():
    expected = {A, B}
    ranked = [X, A, B]
    assert recall_at_k(expected, ranked, 1) == 0
    assert recall_at_k(expected, ranked, 2) == 0.5
    assert recall_at_k(expected, ranked, 3) == 1
    assert reciprocal_rank_at_k(expected, ranked, 1) == 0
    assert reciprocal_rank_at_k(expected, ranked, 3) == 0.5


def test_wrong_source_and_duplicate_hits_cannot_inflate_recall():
    assert recall_at_k({A}, [X], 5) == 0
    assert recall_at_k({A, B}, [A, A, A], 3) == 0.5
    assert recall_at_k({A}, [], 5) == 0
    assert reciprocal_rank_at_k({A}, [], 5) == 0


@pytest.mark.parametrize("expected,k", [(set(), 5), ({A}, 0), ({A}, -1)])
def test_invalid_metrics_are_not_fabricated(expected, k):
    with pytest.raises(ValueError):
        recall_at_k(expected, [], k)
    with pytest.raises(ValueError):
        reciprocal_rank_at_k(expected, [], k)


def test_macro_average_and_empty_group():
    rows = [
        {"recall_at_k": {"3": 0.5}, "reciprocal_rank_at_k": {"3": 0.5}},
        {"recall_at_k": {"3": 1}, "reciprocal_rank_at_k": {"3": 1}},
    ]
    assert aggregate(rows, [3])["recall_at_k"]["3"] == 0.75
    assert aggregate(rows, [3])["mrr_at_k"]["3"] == 0.75
    assert aggregate([], [3])["recall_at_k"] is None
