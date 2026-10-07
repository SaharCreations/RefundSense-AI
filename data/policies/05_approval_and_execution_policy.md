# SampleCo Retail — Refund Approval & Execution Policy
Version: 1.0
Effective date: 2026-09-01
Status: CURRENT

## AE-1 Human Approval Required
Any refund that writes to the transaction system requires explicit human approval.

## AE-2 Exact Payload
The approval screen must show the exact order ID, customer ID, refund amount, payment method, and action to be executed.

## AE-3 Revalidation
Immediately before execution, the system must re-read the current order state and re-run deterministic refund rules.

## AE-4 Approval Expiry
An approval expires 15 minutes after it is granted.

## AE-5 Idempotency
Every refund execution must include a unique idempotency key. Reusing the same approval must not create a second refund.

## AE-6 Authorization
The order must belong to the requester's organization. A user must not approve or access another organization's order.
