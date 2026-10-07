import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from refundguard.rules import RecordUnavailable, RefundRequest, Ruleset, assess_refund, exact_id
from refundguard.rules_evaluation import case_inputs, load_cases

ROOT = Path(__file__).resolve().parents[1]
DATA = load_cases(ROOT / "data/rules_eval_cases.json")
DEV_CASES = [c for c in DATA["cases"] if c["split"] == "dev"]


@pytest.fixture
def ruleset():
    return Ruleset(ROOT / "config/demo_ruleset.json", ROOT / "data/policies")


@pytest.mark.parametrize("case", DEV_CASES, ids=lambda c: c["id"])
def test_hand_labeled_development_cases(case, ruleset):
    result = assess_refund(*case_inputs(DATA, case), ruleset)
    assert {key: result[key] for key in case["expected"]} == case["expected"]
    assert result["execution_allowed"] is False
    assert result["human_approval_required_for_execution"] is True
    assert result["citations"]
    if result["decision"] != "eligible":
        assert result["candidate_payload"] is None


@pytest.mark.parametrize("value", ["", " ", " ORD-1001", "ORD-1001 ", "ORD\n1001", None, 1001])
def test_exact_ids_are_never_guessed_or_normalized(value):
    with pytest.raises(ValueError):
        exact_id(value)


def test_small_money_and_cap_invariants_use_integer_cents(ruleset):
    principal, customer, order, request = case_inputs(DATA, DATA["cases"][3])
    for paid in range(1, 501):
        result = assess_refund(
            principal, customer, replace(order, paid_minor=paid), request, ruleset
        )
        assert type(result["refund_amount_minor"]) is int
        assert type(result["restocking_fee_minor"]) is int
        assert result["refund_amount_minor"] + result["restocking_fee_minor"] == paid
        assert 0 <= result["refund_amount_minor"] <= paid


@pytest.mark.parametrize("money", [-1, 1.5, True, 2**63])
def test_invalid_money_never_produces_a_candidate(money, ruleset):
    principal, customer, order, request = case_inputs(DATA, DATA["cases"][0])
    result = assess_refund(principal, customer, replace(order, paid_minor=money), request, ruleset)
    assert result["decision"] == "review"
    assert result["reason_code"] == "invalid_money_state"
    assert result["candidate_payload"] is None


def test_unknown_reason_and_warranty_are_not_new_refund_rules(ruleset):
    principal, customer, order, request = case_inputs(DATA, DATA["cases"][0])
    result = assess_refund(
        principal, customer, order, replace(request, reason="subscription_cancel"), ruleset
    )
    assert result["reason_code"] == "unsupported_request_reason"
    result = assess_refund(principal, customer, order, replace(request, reason="warranty"), ruleset)
    assert result["decision"] == "review"
    assert {c["section"] for c in result["citations"]} == {"WP-2", "WP-3"}


def test_damage_date_boundaries_and_missing_verification(ruleset):
    principal, customer, order, request = case_inputs(DATA, DATA["cases"][7])
    request = replace(request, requested_on=date(2026, 10, 10))
    day7 = assess_refund(
        principal, customer, replace(order, damage_reported_on=date(2026, 10, 8)), request, ruleset
    )
    day8 = assess_refund(
        principal, customer, replace(order, damage_reported_on=date(2026, 10, 9)), request, ruleset
    )
    assert day7["decision"] == "eligible" and day8["decision"] == "ineligible"
    missing = assess_refund(
        principal, customer, replace(order, damage_on_arrival_verified=None), request, ruleset
    )
    assert missing["reason_code"] == "damage_verification_missing"


def test_policy_edit_requires_rule_review(tmp_path, ruleset):
    import shutil

    folder = tmp_path / "policies"
    shutil.copytree(ROOT / "data/policies", folder)
    policy = folder / "01_refund_policy_current.md"
    policy.write_text(policy.read_text().replace("15%", "20%"))
    with pytest.raises(ValueError, match="Policy bundle changed"):
        Ruleset(ROOT / "config/demo_ruleset.json", folder)


def test_premium_must_be_boolean_not_customer_wording(ruleset):
    principal, customer, order, request = case_inputs(DATA, DATA["cases"][3])
    result = assess_refund(
        principal, replace(customer, premium_verified="yes"), order, request, ruleset
    )
    assert result["reason_code"] == "invalid_record_field_types"


def test_wrong_customer_cannot_assess_an_order(ruleset):
    principal, customer, order, request = case_inputs(DATA, DATA["cases"][0])
    with pytest.raises(RecordUnavailable):
        assess_refund(
            principal, customer, order, replace(request, customer_id="CUST-OTHER"), ruleset
        )


def test_config_conventions_are_explicit_and_not_silent_defaults(tmp_path):
    data = json.loads((ROOT / "config/demo_ruleset.json").read_text())
    data["conventions"]["restocking_rounding"] = "floor"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Unsupported rules configuration"):
        Ruleset(path, ROOT / "data/policies")


def test_scope_uses_exact_identifiers():
    with pytest.raises(ValueError):
        RefundRequest(" ORD-1001 ", "CUST-1001", date(2026, 10, 6))
