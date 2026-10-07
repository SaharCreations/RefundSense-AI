# Deterministic assessment milestone

The rules engine reads exact customer and order records from relational SQL,
then returns `eligible`, `ineligible`, or `review`. It never uses retrieval ranks,
an LLM answer, or user prose as a source of monetary facts. It has no payment
execution method. Every output includes `execution_allowed: false`.

This is a deliberately bounded synthetic demo for one supported physical item
with no prior refund, using USD cents. It is not a general refund engine for all
possible commerce transactions. The ruleset is pinned to the supplied current
refund, Premium, shipping, and warranty documents. A source-file change blocks
assessment until the deterministic rules/configuration are reviewed together.

## Policy rules and explicit demo conventions

The supplied documents define a 30-calendar-day normal window, a 15% fee for
opened electronics, a verified-Premium waiver, a seven-day damaged-on-arrival
reporting exception, final-sale limits, and the original-payment-method cap.

They do not define every calculation detail. The following are **implementation
conventions for the synthetic demo**, recorded in `config/demo_ruleset.json`,
included in every result, and validated against the implemented rules version:

- Delivery is day zero; day 30 and damage-report day 7 are included.
- Ordinary full-item refunds use the item's amount actually paid minus a fee.
- The fee base excludes tax and outbound shipping.
- USD amounts use integer cents. Restocking fees round half up to one cent.
- Unknown currencies, multiple items, tax treatment, store credit, partially
  refunded orders, and unsupported products/reasons require review.

These conventions are not presented as missing company-policy clauses. They
need a business-approved specification before real payment execution is added.
No policy document or original retrieval evaluation label was changed.

## Precedence and unresolved cases

1. Verify the exact organization, customer, and order identifiers.
2. Check governing-policy binding and record/money consistency.
3. Pause for unknown payment state, an existing refund, unsupported method,
   missing facts, or a situation beyond the supported demo scope.
4. Route carrier-lost orders to shipment resolution.
5. A verified damage report within seven days can override final sale and the
   normal return window. No extra deadline after a timely report is invented.
6. Without that exception, final sale is ineligible and the normal return window
   ends after day 30. Premium does not extend it.
7. Apply the opened-electronics fee or the SQL-verified Premium waiver.
8. Cap the candidate amount at the item's paid amount and preserve the original
   payment reference.

The policies do not say whether damage waives the normal opened-electronics fee
for non-Premium customers. That combination returns `review` with no candidate
amount. Premium status comes from the customer record; a missing or non-boolean
value is never interpreted as a membership claim. Missing damage verification
does not become a damage exception.

The policy bundle ID is an explicit SQL record attribute, not selected by an LLM
or inferred from delivery date. Current rules are not silently applied to orders
bound to a historical bundle. Adding a production ingestion/admin process for
that policy binding is later work.

## SQL scope and snapshots

`customers` and `orders` are separate relational PostgreSQL tables. A composite
foreign key prevents an order's customer from belonging to another organization.
The loader joins them using exact organization/order/customer predicates with
bound SQL parameters. Wrong customer, unknown order, and cross-organization
access return the same unavailable-record error. No fuzzy or fallback lookup
exists.

Assessment uses a read-only repeatable-read transaction. Record revisions change
automatically on updates. The result preserves order/customer revisions and a
hash of the exact facts/request used. Those are assessment snapshots, not a
substitute for revalidation immediately before eventual execution.

The CLI `--organization-id` is a local demo scope. It is **not authentication**.
A future FastAPI service must derive the principal from authenticated identity,
never a request/LLM-provided organization ID. Neither authentication nor payment
execution is claimed by this milestone.

## Run the demo

After setting `DATABASE_URL` and installing the locked dependencies:

```bash
uv run refundguard seed-demo
```

This adds five clearly synthetic orders for `ORG-DEMO`. Re-running it never
overwrites existing records.

```bash
uv run refundguard assess --organization-id ORG-DEMO --customer-id CUST-1001 --order-id ORD-1002 --requested-on 2026-10-06
```

That example reads the opened-electronics order from SQL and returns a candidate
refund of 8,500 cents ($85) and a 1,500-cent ($15) fee on a $100 item. Approval is
still required for any future execution.

```bash
uv run refundguard assess --organization-id ORG-DEMO --customer-id CUST-1002 --order-id ORD-1003 --requested-on 2026-10-06
```

That order belongs to the verified-Premium customer and yields a $100 candidate
refund with no restocking fee. `ORD-1004` is final sale. `ORD-1005` has a verified,
timely damage report and can be assessed with `--reason damaged_on_arrival`.

To reproduce the rules evaluation:

```bash
uv run refundguard evaluate-rules --split dev
uv run refundguard evaluate-rules --split heldout
```

The rules dataset is separate from the original 30 RAG questions. It contains
30 hand-labeled synthetic cases, split into 20 development and 10 held-out cases
before scoring. Only development cases are used by the parametrized regression
test. General boundary/invariant tests also cover dates and integer money; this
is not a blind external evaluation.

Accuracy is an exact match of decision, reason code, refund cents, and fee cents.
The observed result was 20/20 development and 10/10 held out. This narrow result
does not measure correctness for every possible real order or payment action.

## Evidence and remaining work

`reports/rules_v1/` contains the measured scenarios, complete SQL-backed example
outputs, the test report, and verification metadata. The complete suite finished
with 71 tests passing and one native-PostgreSQL test skipped in the PostgreSQL
WASM test harness. The native database gate from the retrieval milestone remains.

The initial RAG results remain archived under `reports/baseline_v1/`; their
rules-engine accuracy stays null because that engine did not exist at the time.
The new rules reports provide this milestone's separate measured accuracy.

At this assessment milestone, execution was not implemented. Persistent
LangGraph approval, payload confirmation, expiry, idempotent demo execution,
live-state revalidation, and append-only audit records are now implemented in
the subsequent [approval workflow milestone](approval_workflow.md). The archived
rules reports retain their original read-only assessment scope. Grounded AI
explanations, abstention checks, the Next.js
interface, and a real payment integration remain later work.
FastAPI authentication/routes are now implemented for the local demo in [api.md](api.md).
