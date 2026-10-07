"""Deterministic, read-only assessments for a pinned synthetic policy bundle.

No language model, retrieval rank, user prose, or payment writer participates.
Amounts are integer cents. Eligibility is not approval or permission to execute.
"""

import json
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .corpus import Chunk, json_hash, load_corpus

BUNDLE_ID = "sampleco-september-2026"
RULES_VERSION = "demo-assessment-v1"
RF = "01_refund_policy_current.md"
PC = "04_premium_customer_policy.md"
SH = "07_shipping_policy.md"
WP = "03_warranty_policy.md"
CONVENTIONS = {
    "status": "synthetic_demo_only",
    "currency": "USD",
    "money_unit": "integer_cents",
    "restocking_base": "item_amount_actually_paid_excluding_shipping_and_tax",
    "restocking_rounding": "half_up_to_one_cent",
    "delivery_day": "day_zero",
    "standard_window_last_day": "delivery_plus_30_calendar_days_inclusive",
    "damage_reporting_last_day": "delivery_plus_7_calendar_days_inclusive",
    "ordinary_refund": "item_amount_paid_minus_applicable_restocking_fee",
    "scope": "one_physical_item_full_return_only",
}


def exact_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 64
        or value != value.strip()
        or any(unicodedata.category(c).startswith("C") for c in value)
    ):
        raise ValueError("Provide an exact, nonempty ID without surrounding whitespace")
    return value


class RecordUnavailable(ValueError):
    """Same error for an absent record, wrong customer, or unauthorized organization."""


@dataclass(frozen=True)
class Principal:
    organization_id: str

    def __post_init__(self):
        exact_id(self.organization_id)


@dataclass(frozen=True)
class Customer:
    organization_id: str
    customer_id: str
    premium_verified: bool | None
    revision: int = 1


@dataclass(frozen=True)
class Order:
    organization_id: str
    order_id: str
    customer_id: str
    policy_bundle_id: str
    product_type: str
    item_count: int
    delivered_on: date | None
    delivery_status: str
    opened: bool | None
    final_sale: bool | None
    damage_on_arrival_verified: bool | None
    damage_reported_on: date | None
    paid_minor: int
    refunded_minor: int
    currency: str
    payment_status: str
    payment_method: str | None
    payment_reference: str | None
    refund_state: str
    revision: int = 1


@dataclass(frozen=True)
class RefundRequest:
    order_id: str
    customer_id: str
    requested_on: date
    reason: str = "standard_return"
    refund_method: str = "original_payment"
    include_shipping: bool = False
    include_tax: bool = False

    def __post_init__(self):
        exact_id(self.order_id)
        exact_id(self.customer_id)
        if type(self.requested_on) is not date:
            raise ValueError("requested_on must be a calendar date supplied by the application")
        if (
            not isinstance(self.reason, str)
            or not isinstance(self.refund_method, str)
            or type(self.include_shipping) is not bool
            or type(self.include_tax) is not bool
        ):
            raise ValueError("Request fields must use explicit strings and booleans")


class Ruleset:
    def __init__(self, config_path: Path, policies_path: Path):
        self.config = json.loads(config_path.read_text())
        if (
            self.config.get("bundle_id") != BUNDLE_ID
            or self.config.get("rules_version") != RULES_VERSION
            or self.config.get("conventions") != CONVENTIONS
        ):
            raise ValueError("Unsupported rules configuration; explicit code review is required")
        self.chunks = load_corpus(policies_path)
        self.sources = self.config["policy_source_sha256"]
        for source, expected_hash in self.sources.items():
            matches = [c for c in self.chunks if c.source == source]
            if not matches or any(
                c.source_sha256 != expected_hash or c.status != "CURRENT" for c in matches
            ):
                raise ValueError("Policy bundle changed; re-review deterministic rules before use")
        if not {RF, PC, SH, WP} <= set(self.sources):
            raise ValueError("Rules configuration lacks required policies")
        self.fingerprint = json_hash(self.config)

    def citation(self, source: str, section: str) -> dict:
        chunk: Chunk = next(c for c in self.chunks if c.label == (source, section))
        return {
            "source": source,
            "section": section,
            "version": chunk.version,
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
            "source_sha256": chunk.source_sha256,
        }


def assess_refund(
    principal: Principal,
    customer: Customer,
    order: Order,
    request: RefundRequest,
    ruleset: Ruleset,
) -> dict:
    if (
        principal.organization_id != customer.organization_id
        or principal.organization_id != order.organization_id
        or customer.customer_id != order.customer_id
        or request.customer_id != customer.customer_id
        or request.order_id != order.order_id
    ):
        raise RecordUnavailable("Order/customer is not available in the authorized organization")

    def result(decision: str, code: str, refs: list[tuple[str, str]], fee: int | None = None):
        amount = order.paid_minor - fee if fee is not None else None
        payload = None
        if decision == "eligible":
            if amount is None or not 0 <= amount <= order.paid_minor:
                raise ValueError("Refund amount violates the deterministic payment cap")
            payload = {
                "action": "refund",
                "organization_id": order.organization_id,
                "order_id": order.order_id,
                "customer_id": customer.customer_id,
                "refund_amount_minor": amount,
                "restocking_fee_minor": fee,
                "currency": order.currency,
                "payment_method": order.payment_method,
                "original_payment_reference": order.payment_reference,
            }
        return {
            "decision": decision,
            "reason_code": code,
            "refund_amount_minor": amount,
            "restocking_fee_minor": fee,
            "currency": order.currency,
            "candidate_payload": payload,
            "assessment_only": True,
            "execution_allowed": False,
            "human_approval_required_for_execution": True,
            "rules_version": RULES_VERSION,
            "ruleset_fingerprint": ruleset.fingerprint,
            "conventions": dict(CONVENTIONS),
            "citations": [ruleset.citation(source, section) for source, section in refs],
            "snapshot": {
                "order_revision": order.revision,
                "customer_revision": customer.revision,
                "requested_on": request.requested_on.isoformat(),
                "facts_sha256": json_hash(
                    json.loads(
                        json.dumps(
                            {
                                "order": asdict(order),
                                "customer": asdict(customer),
                                "request": asdict(request),
                            },
                            default=lambda d: d.isoformat(),
                        )
                    )
                ),
            },
        }

    def review(code: str, refs=None):
        return result("review", code, refs or [(RF, "RP-7")])

    flags = [
        order.opened,
        order.final_sale,
        order.damage_on_arrival_verified,
        customer.premium_verified,
    ]
    dates = [order.delivered_on, order.damage_reported_on]
    if (
        any(value is not None and type(value) is not bool for value in flags)
        or any(value is not None and type(value) is not date for value in dates)
        or type(order.item_count) is not int
        or order.item_count < 1
        or type(order.revision) is not int
        or order.revision < 1
        or type(customer.revision) is not int
        or customer.revision < 1
    ):
        return review("invalid_record_field_types")
    if order.policy_bundle_id != BUNDLE_ID or request.requested_on < date(2026, 9, 1):
        return review("unsupported_policy_bundle")
    if (
        type(order.paid_minor) is not int
        or type(order.refunded_minor) is not int
        or not 0 <= order.refunded_minor <= order.paid_minor <= 2**63 - 1
    ):
        return review("invalid_money_state")
    if order.currency != "USD":
        return review("unsupported_currency")
    if order.paid_minor == 0 or order.refunded_minor == order.paid_minor:
        return result("ineligible", "nothing_remaining_to_refund", [(RF, "RP-5")])
    if order.refunded_minor > 0:
        return review("partial_refund_history_needs_review", [(RF, "RP-5"), (RF, "RP-7")])
    if order.refund_state != "none":
        return review("existing_refund_state_needs_review")
    if order.payment_status != "paid":
        return review("payment_state_needs_review")
    if not order.payment_method or not order.payment_reference:
        return review("original_payment_details_missing", [(RF, "RP-5")])
    if request.refund_method != "original_payment":
        return review("unsupported_refund_method", [(RF, "RP-5"), (RF, "RP-7")])
    if request.include_shipping:
        return review("shipping_refund_not_authorized", [(SH, "SP-2")])
    if request.include_tax:
        return review("tax_refund_policy_missing")
    if request.reason == "warranty":
        return review("warranty_is_separate", [(WP, "WP-2"), (WP, "WP-3")])
    if order.product_type not in {"ordinary", "electronics"} or order.item_count != 1:
        return review("unsupported_product_or_multi_item_order")
    if request.reason not in {"standard_return", "damaged_on_arrival"}:
        return review("unsupported_request_reason")
    if order.delivery_status == "lost":
        return review("use_shipment_resolution", [(SH, "SP-3")])
    if order.delivery_status != "delivered" or order.delivered_on is None:
        return review("delivery_facts_missing")
    days = (request.requested_on - order.delivered_on).days
    if days < 0:
        return review("delivery_date_in_future")
    if order.final_sale is None:
        return review("final_sale_flag_missing")

    damage_exception = False
    if request.reason == "damaged_on_arrival":
        if order.damage_on_arrival_verified is None:
            return review("damage_verification_missing", [(RF, "RP-6"), (RF, "RP-7")])
        if order.damage_on_arrival_verified:
            if order.damage_reported_on is None:
                return review("damage_report_date_missing", [(RF, "RP-6")])
            reported_days = (order.damage_reported_on - order.delivered_on).days
            if reported_days < 0 or order.damage_reported_on > request.requested_on:
                return review("invalid_damage_report_date", [(RF, "RP-6")])
            damage_exception = reported_days <= 7
    if order.final_sale and not damage_exception:
        return result("ineligible", "final_sale_without_timely_damage_exception", [(RF, "RP-4")])
    if days > 30 and not damage_exception:
        return result("ineligible", "return_window_expired", [(RF, "RP-1"), (PC, "PC-3")])

    refs = [(RF, "RP-6")] if damage_exception else [(RF, "RP-1")]
    fee = 0
    if order.product_type == "electronics":
        if order.opened is None:
            return review("opened_flag_missing", [(RF, "RP-2"), (RF, "RP-7")])
        if order.opened:
            if customer.premium_verified is None:
                return review("premium_record_status_missing", [(PC, "PC-1")])
            if customer.premium_verified:
                refs += [(RF, "RP-3"), (PC, "PC-2")]
            elif damage_exception:
                return review(
                    "damaged_opened_electronics_fee_undefined",
                    [(RF, "RP-2"), (RF, "RP-6"), (RF, "RP-7")],
                )
            else:
                # 15% of integer cents, half up; no float arithmetic.
                fee = (order.paid_minor * 15 + 50) // 100
                refs += [(RF, "RP-2")]
    refs += [(RF, "RP-5")]
    return result(
        "eligible",
        "damaged_on_arrival_exception" if damage_exception else "standard_return_eligible",
        refs,
        fee,
    )
