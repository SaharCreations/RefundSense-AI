"""Exact, organization-scoped SQL reads. No fuzzy matching or RAG order facts."""

from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .rules import Customer, Order, Principal, RecordUnavailable, RefundRequest, exact_id

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS refundguard;
CREATE TABLE IF NOT EXISTS refundguard.customers (
    organization_id text NOT NULL,
    customer_id text NOT NULL,
    premium_verified boolean,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    PRIMARY KEY (organization_id, customer_id)
);
CREATE TABLE IF NOT EXISTS refundguard.orders (
    organization_id text NOT NULL,
    order_id text NOT NULL,
    customer_id text NOT NULL,
    policy_bundle_id text NOT NULL,
    product_type text NOT NULL,
    item_count integer NOT NULL CHECK (item_count > 0),
    delivered_on date,
    delivery_status text NOT NULL,
    opened boolean,
    final_sale boolean,
    damage_on_arrival_verified boolean,
    damage_reported_on date,
    paid_minor bigint NOT NULL CHECK (paid_minor >= 0),
    refunded_minor bigint NOT NULL DEFAULT 0 CHECK (refunded_minor >= 0),
    currency text NOT NULL,
    payment_status text NOT NULL,
    payment_method text,
    payment_reference text,
    refund_state text NOT NULL DEFAULT 'none',
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    PRIMARY KEY (organization_id, order_id),
    FOREIGN KEY (organization_id, customer_id)
        REFERENCES refundguard.customers (organization_id, customer_id),
    CHECK (refunded_minor <= paid_minor)
);
CREATE OR REPLACE FUNCTION refundguard.bump_revision() RETURNS trigger AS $$
BEGIN
    NEW.revision := OLD.revision + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER customer_revision_update BEFORE UPDATE ON refundguard.customers
FOR EACH ROW EXECUTE FUNCTION refundguard.bump_revision();
CREATE OR REPLACE TRIGGER order_revision_update BEFORE UPDATE ON refundguard.orders
FOR EACH ROW EXECUTE FUNCTION refundguard.bump_revision();
"""


@contextmanager
def order_connection(database_url: str, read_only: bool = True):
    with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=10) as conn:
        if read_only:
            # One joined SQL read provides order/customer facts from one snapshot.
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield conn


def read_order_customer(
    conn, principal: Principal, request: RefundRequest
) -> tuple[Order, Customer]:
    exact_id(principal.organization_id)
    row = conn.execute(
        """SELECT o.*, c.premium_verified, c.revision AS customer_revision
        FROM refundguard.orders o
        JOIN refundguard.customers c
          ON c.organization_id = o.organization_id AND c.customer_id = o.customer_id
        WHERE o.organization_id = %s AND o.order_id = %s AND o.customer_id = %s""",
        (principal.organization_id, request.order_id, request.customer_id),
    ).fetchone()
    if row is None:
        raise RecordUnavailable("Order/customer is not available in the authorized organization")
    customer = Customer(
        row["organization_id"],
        row["customer_id"],
        row["premium_verified"],
        row["customer_revision"],
    )
    facts = {key: row[key] for key in Order.__dataclass_fields__}
    return Order(**facts), customer


def seed_demo(conn, orders: list[Order], customers: list[Customer]) -> None:
    """Only explicitly supplied demo records; never overwrite existing live state."""
    if any(x.organization_id != "ORG-DEMO" for x in [*orders, *customers]):
        raise ValueError("Demo seeding is restricted to ORG-DEMO")
    conn.execute(SCHEMA)
    for c in customers:
        conn.execute(
            """INSERT INTO refundguard.customers
            (organization_id, customer_id, premium_verified, revision) VALUES (%s, %s, %s, %s)
            ON CONFLICT (organization_id, customer_id) DO NOTHING""",
            (c.organization_id, c.customer_id, c.premium_verified, c.revision),
        )
    for order in orders:
        fields = list(Order.__dataclass_fields__)
        # Column identifiers are from the fixed dataclass, never user/model text.
        from psycopg import sql

        statement = sql.SQL(
            "INSERT INTO refundguard.orders ({}) VALUES ({}) "
            "ON CONFLICT (organization_id, order_id) DO NOTHING"
        ).format(
            sql.SQL(", ").join(map(sql.Identifier, fields)),
            sql.SQL(", ").join(sql.Placeholder() for _ in fields),
        )
        conn.execute(statement, tuple(getattr(order, key) for key in fields))
