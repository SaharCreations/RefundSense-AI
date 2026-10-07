"""Resolve gold labels without ever passing them to retrieval."""

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from .corpus import Chunk


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    question: str
    expected: frozenset[tuple[str, str]]
    expected_answer: str
    expected_behavior: str


def load_questions(path: Path, chunks: list[Chunk]) -> list[Question]:
    available = {c.label for c in chunks}
    questions, ids = [], set()
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fields = {
            "id",
            "category",
            "question",
            "expected_source",
            "expected_section",
            "expected_answer",
            "expected_behavior",
        }
        if not fields.issubset(reader.fieldnames or []):
            raise ValueError("Evaluation CSV is missing required fields")
        for row in reader:
            if any(not row[f] or not row[f].strip() for f in fields):
                raise ValueError("Evaluation row has an empty field")
            if row["id"] in ids:
                raise ValueError(f"Duplicate evaluation ID: {row['id']}")
            ids.add(row["id"])
            if row["expected_behavior"] not in {"answer", "abstain"}:
                raise ValueError(f"{row['id']}: unsupported behavior")
            sources = [s.strip() for s in row["expected_source"].split(";")]
            sections = [s.strip() for s in row["expected_section"].split(";")]
            if len(sources) == 1:
                labels = [(sources[0], section) for section in sections]
            elif len(sources) == len(sections):
                labels = list(zip(sources, sections, strict=True))
            else:
                raise ValueError(f"{row['id']}: ambiguous source/section mapping")
            if len(set(labels)) != len(labels):
                raise ValueError(f"{row['id']}: duplicate gold label")
            missing = set(labels) - available
            if missing:
                raise ValueError(f"{row['id']}: gold labels absent from corpus: {sorted(missing)}")
            questions.append(
                Question(
                    id=row["id"],
                    category=row["category"],
                    question=row["question"],
                    expected=frozenset(labels),
                    expected_answer=row["expected_answer"],
                    expected_behavior=row["expected_behavior"],
                )
            )
    if not questions:
        raise ValueError("Evaluation dataset is empty")
    return questions


def load_splits(path: Path, questions: list[Question]) -> dict:
    split = json.loads(path.read_text())
    for key in ("dev", "heldout"):
        if not isinstance(split.get(key), list) or not split[key]:
            raise ValueError(f"Split {key} must be a nonempty list")
    dev, heldout = split["dev"], split["heldout"]
    if len(set(dev)) != len(dev) or len(set(heldout)) != len(heldout):
        raise ValueError("Duplicate IDs in split")
    if set(dev) & set(heldout):
        raise ValueError("Development and held-out splits overlap")
    if set(dev) | set(heldout) != {q.id for q in questions}:
        raise ValueError("Splits must cover exactly the evaluation IDs")
    return split
