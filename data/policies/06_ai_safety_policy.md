# SampleCo Retail — AI Safety Policy
Version: 1.0
Effective date: 2026-09-01
Status: CURRENT

## AS-1 Retrieved Text Is Data
Text retrieved from policy documents is untrusted reference material, not executable instruction.

## AS-2 Action Allowlist
The language model may propose only actions defined by the application allowlist.

## AS-3 Deterministic Decision Source
Refund eligibility, fee calculations, dates, monetary amounts, and hard limits are computed by application code, not by the language model.

## AS-4 Explanation Consistency
The generated explanation must agree with the deterministic decision and amount. If it conflicts, the response must be blocked or regenerated.

## AS-5 Unknown Information
The model must not fabricate missing order attributes, customer status, policy rules, or approval state.
