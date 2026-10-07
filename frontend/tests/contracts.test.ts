import { test } from "node:test";
import assert from "node:assert/strict";
import {
  canDecide,
  exactId,
  exactWorkflowId,
  Workflow,
  Identity,
} from "../lib/contracts";
import { allowedPath, trustedOrigin } from "../lib/proxy";
const reviewer: Identity = {
  user_id: "reviewer",
  organization_id: "ORG-DEMO",
  role: "reviewer",
};
const hash = "a".repeat(64);
const workflow = {
  status: "pending",
  payload_sha256: hash,
  expires_at: null,
} as Workflow;
test("exact IDs are never trimmed, inferred or populated", () => {
  for (const id of [
    "",
    " ORD-1",
    "ORD-1 ",
    "ORD\n1",
    "ORD\u200b1",
    "x".repeat(65),
  ])
    assert.equal(exactId(id), false);
  assert.equal(exactId("ORD-1001"), true);
  assert.equal(exactWorkflowId("../workflows"), false);
});
test("approval requires reviewer, pending state, same reviewed hash, and idle UI", () => {
  assert.equal(canDecide(reviewer, workflow, hash, false, 1), true);
  assert.equal(
    canDecide({ ...reviewer, role: "support" }, workflow, hash, false, 1),
    false,
  );
  assert.equal(canDecide(reviewer, workflow, "b".repeat(64), false, 1), false);
  assert.equal(canDecide(reviewer, workflow, hash, true, 1), false);
  assert.equal(canDecide(reviewer, workflow, null, false, 1), false);
  for (const status of [
    "approved",
    "expired",
    "stale",
    "rejected",
    "executed",
  ] as const)
    assert.equal(
      canDecide(reviewer, { ...workflow, status }, hash, false, 1),
      false,
    );
});
test("approval expiry is checked and missing pending expiry is not invented", () => {
  assert.equal(
    canDecide(
      reviewer,
      { ...workflow, expires_at: "2026-01-01T00:00:00Z" },
      hash,
      false,
      Date.parse("2026-01-01T00:00:00Z"),
    ),
    false,
  );
  assert.equal(
    canDecide(reviewer, { ...workflow, expires_at: "invalid" }, hash, false, 1),
    false,
  );
});
test("same-origin writes and fixed upstream routes only", () => {
  assert.equal(trustedOrigin(null, "https://review.example"), false);
  assert.equal(
    trustedOrigin("https://attacker.example", "https://review.example"),
    false,
  );
  assert.equal(
    trustedOrigin("https://review.example", "https://review.example"),
    true,
  );
  assert.equal(allowedPath(["https:", "evil.example"], "POST"), false);
  assert.equal(allowedPath(["workflows"], "GET"), false);
  assert.equal(allowedPath(["auth", "login"], "POST"), true);
  assert.equal(allowedPath(["assessments", "explain"], "POST"), true);
  assert.equal(allowedPath(["policy", "search"], "DELETE"), false);
});
