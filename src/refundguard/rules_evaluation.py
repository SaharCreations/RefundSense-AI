"""Hand-labeled synthetic rule scenarios, separate from the RAG query dataset."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

from .corpus import sha256
from .rules import (
    Customer,
    Order,
    Principal,
    RecordUnavailable,
    RefundRequest,
    Ruleset,
    assess_refund,
)


def order_from_dict(facts: dict) -> Order:
    values = dict(facts)
    for field in ["delivered_on", "damage_reported_on"]:
        if values.get(field) is not None:
            values[field] = date.fromisoformat(values[field])
    return Order(**values)


def request_from_dict(facts: dict) -> RefundRequest:
    values = dict(facts)
    values["requested_on"] = date.fromisoformat(values["requested_on"])
    return RefundRequest(**values)


def load_cases(path: Path) -> dict:
    data = json.loads(path.read_text())
    ids = [case["id"] for case in data["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate rules evaluation IDs")
    if any(c["split"] not in {"dev", "heldout"} for c in data["cases"]):
        raise ValueError("Unknown rules evaluation split")
    for case in data["cases"]:
        expected = case["expected"]
        if set(expected) != {
            "decision",
            "reason_code",
            "refund_amount_minor",
            "restocking_fee_minor",
        }:
            raise ValueError("Each rules case must label all four exact-match fields")
    return data


def case_inputs(data: dict, case: dict):
    customer = Customer(**{**data["base_customer"], **case.get("customer", {})})
    order = order_from_dict({**data["base_order"], **case.get("order", {})})
    request = request_from_dict({**data["base_request"], **case.get("request", {})})
    principal = Principal(case.get("organization_id", data["base_order"]["organization_id"]))
    return principal, customer, order, request


def score_cases(path: Path, ruleset: Ruleset, split: str) -> dict:
    data = load_cases(path)
    if split not in {"dev", "heldout", "all"}:
        raise ValueError("Unknown split")
    selected = [c for c in data["cases"] if split == "all" or c["split"] == split]
    if not selected:
        raise ValueError("Cannot score an empty split")
    results = []
    for case in selected:
        try:
            assessment = assess_refund(*case_inputs(data, case), ruleset)
            actual = {key: assessment[key] for key in case["expected"]}
        except RecordUnavailable:
            actual = {
                "decision": "unavailable",
                "reason_code": "record_unavailable",
                "refund_amount_minor": None,
                "restocking_fee_minor": None,
            }
        results.append(
            {
                "id": case["id"],
                "description": case["description"],
                "expected": case["expected"],
                "actual": actual,
                "passed": actual == case["expected"],
            }
        )
    passed = sum(r["passed"] for r in results)
    return {
        "status": "measured",
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "split": split,
        "count": len(results),
        "passed": passed,
        "rules_engine_accuracy": passed / len(results),
        "definition": "Exact match of decision, reason code, refund cents, and fee cents.",
        "case_data_sha256": sha256(path.read_bytes()),
        "ruleset_fingerprint": ruleset.fingerprint,
        "conventions": ruleset.config["conventions"],
        "limitations": data["limitations"],
        "cases": results,
    }
