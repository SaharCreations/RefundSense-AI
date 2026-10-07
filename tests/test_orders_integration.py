import json
import os
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from refundguard.orders import order_connection, read_order_customer, seed_demo
from refundguard.rules import Customer, Principal, RecordUnavailable, RefundRequest
from refundguard.rules_evaluation import order_from_dict

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def seeded_orders():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    records = json.loads((ROOT / "data/demo_records.json").read_text())
    # Separate IDs from the CLI demo so fixture data never overwrites real/demo rows.
    customers = [Customer(**facts) for facts in records["customers"]]
    customers = [replace(c, customer_id=c.customer_id + "-TEST") for c in customers]
    orders = [order_from_dict(facts) for facts in records["orders"]]
    orders = [
        replace(o, order_id=o.order_id + "-TEST", customer_id=o.customer_id + "-TEST")
        for o in orders
    ]
    with order_connection(url, read_only=False) as conn:
        seed_demo(conn, orders, customers)
        yield conn
        conn.rollback()


def request(order_id="ORD-1001-TEST", customer_id="CUST-1001-TEST"):
    return RefundRequest(order_id, customer_id, date(2026, 10, 6))


def test_exact_join_reads_original_facts_and_verified_premium(seeded_orders):
    order, customer = read_order_customer(
        seeded_orders, Principal("ORG-DEMO"), request("ORD-1003-TEST", "CUST-1002-TEST")
    )
    assert order.paid_minor == 10000 and order.opened is True
    assert customer.premium_verified is True
    assert order.payment_reference == "DEMO-PAYMENT-1001"


@pytest.mark.parametrize(
    "organization_id,order_id,customer_id",
    [
        ("ORG-OTHER", "ORD-1001-TEST", "CUST-1001-TEST"),
        ("ORG-DEMO", "1001-TEST", "CUST-1001-TEST"),
        ("ORG-DEMO", "ord-1001-test", "CUST-1001-TEST"),
        ("ORG-DEMO", "ORD-1001-TEST", "CUST-1002-TEST"),
        ("ORG-DEMO", "ORD-1001-TEST' OR '1'='1", "CUST-1001-TEST"),
    ],
)
def test_no_guessing_cross_org_access_or_sql_injection(
    seeded_orders,
    organization_id,
    order_id,
    customer_id,
):
    with pytest.raises(RecordUnavailable, match="not available in the authorized organization"):
        read_order_customer(
            seeded_orders, Principal(organization_id), request(order_id, customer_id)
        )


def test_order_revision_changes_and_demo_seed_does_not_overwrite(seeded_orders):
    conn = seeded_orders
    principal, req = Principal("ORG-DEMO"), request()
    before, customer = read_order_customer(conn, principal, req)
    conn.execute(
        "UPDATE refundguard.orders SET refunded_minor = 500 "
        "WHERE organization_id=%s AND order_id=%s",
        (principal.organization_id, req.order_id),
    )
    seed_demo(conn, [before], [customer])
    after, _ = read_order_customer(conn, principal, req)
    assert after.refunded_minor == 500
    assert after.revision == before.revision + 1
