"""Section-level macro Recall@k and truncated MRR@k, with explicit zero misses."""

from collections.abc import Sequence

Label = tuple[str, str]


def recall_at_k(expected: set[Label] | frozenset[Label], ranked: Sequence[Label], k: int) -> float:
    if k < 1 or not expected:
        raise ValueError("k and the number of relevant sections must be positive")
    return len(expected.intersection(ranked[:k])) / len(expected)


def reciprocal_rank_at_k(
    expected: set[Label] | frozenset[Label],
    ranked: Sequence[Label],
    k: int,
) -> float:
    if k < 1 or not expected:
        raise ValueError("k and the number of relevant sections must be positive")
    return next((1.0 / i for i, label in enumerate(ranked[:k], 1) if label in expected), 0.0)


def aggregate(rows: list[dict], ks: list[int]) -> dict:
    if not rows:
        return {"count": 0, "recall_at_k": None, "mrr_at_k": None}
    return {
        "count": len(rows),
        "recall_at_k": {
            str(k): sum(r["recall_at_k"][str(k)] for r in rows) / len(rows) for k in ks
        },
        "mrr_at_k": {
            str(k): sum(r["reciprocal_rank_at_k"][str(k)] for r in rows) / len(rows) for k in ks
        },
    }
