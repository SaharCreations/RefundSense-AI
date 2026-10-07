// HTTP contract fixture only. This does NOT run SQL, LangGraph or model inference.
import http from "node:http";
const hash = "a".repeat(64),
  wid = "00000000-0000-4000-8000-000000000001";
const assessment = {
  decision: "eligible",
  reason_code: "eligible_standard_return",
  refund_amount_minor: 8500,
  restocking_fee_minor: 1500,
  currency: "USD",
  rules_version: "fixture-v1",
  citations: [
    {
      source: "fixture_policy.md",
      section: "Opened electronics",
      line_start: 10,
      line_end: 12,
    },
  ],
  snapshot: {},
};
const workflow = {
  workflow_id: wid,
  status: "pending",
  payload_sha256: hash,
  approval_ttl_seconds: 900,
  expires_at: null,
  exact_execution_payload: {
    execution_target: "demo_ledger",
    idempotency_key: wid,
    refund: {
      action: "refund",
      organization_id: "ORG-DEMO",
      order_id: "ORD-1001",
      customer_id: "CUS-1001",
      refund_amount_minor: 8500,
      restocking_fee_minor: 1500,
      currency: "USD",
      payment_method: "card",
      original_payment_reference: "fixture-payment",
    },
  },
  assessment,
  result: null,
  demo_only: true,
};
let status = "pending",
  decisions = [];
http
  .createServer(async (req, res) => {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : {};
    const role =
      req.headers.authorization === "Bearer fixture-support"
        ? "support"
        : "reviewer";
    const send = (value, code = 200) => {
      res.writeHead(code, { "Content-Type": "application/json" });
      res.end(JSON.stringify(value));
    };
    if (req.url === "/health") return send({ ok: true });
    if (req.url === "/test/reset") {
      status = "pending";
      decisions = [];
      return send({ ok: true });
    }
    if (req.url === "/test/decisions") return send(decisions);
    if (req.url === "/test/stale") {
      status = "stale";
      return send({ ok: true });
    }
    if (req.url === "/api/v1/auth/login")
      return body.password === "fixture-password"
        ? send({ access_token: `fixture-${body.user_id}`, expires_in: 28800 })
        : send({ detail: { code: "invalid_credentials" } }, 401);
    if (!req.headers.authorization)
      return send({ detail: { code: "authentication_required" } }, 401);
    if (req.url === "/api/v1/auth/me")
      return send({ user_id: role, organization_id: "ORG-DEMO", role });
    if (req.url === "/api/v1/auth/logout") {
      res.writeHead(204);
      return res.end();
    }
    if (req.url === "/api/v1/assessments")
      return body.order_id === "ORD-1001" && body.customer_id === "CUS-1001"
        ? send(assessment)
        : send({ detail: { code: "record_unavailable" } }, 404);
    if (req.url === "/api/v1/assessments/explain")
      return send({
        authoritative_assessment: assessment,
        policy_explanation: {
          status: "abstain",
          explanation: "",
          citations: [],
          abstention_reason: "model_abstained",
          execution_allowed: false,
        },
      });
    if (
      req.url === "/api/v1/workflows" ||
      req.url === `/api/v1/workflows/${wid}`
    )
      return send({ ...workflow, status });
    if (req.url === `/api/v1/workflows/${wid}/decisions`) {
      if (role !== "reviewer")
        return send({ detail: { code: "reviewer_required" } }, 403);
      if (status !== "pending" || body.payload_sha256 !== hash)
        return send({ detail: { code: "workflow_conflict" } }, 409);
      decisions.push(body);
      status = body.approved ? "executed" : "rejected";
      return send({
        ...workflow,
        status,
        result: body.approved ? { ledger_reference: "fixture-ledger" } : null,
      });
    }
    if (req.url === `/api/v1/workflows/${wid}/audit`)
      return send({ workflow_id: wid, events: [{ event: "fixture-event" }] });
    if (req.url === "/api/v1/policy/search")
      return send({
        as_of: "2026-10-07",
        retrieved: [
          {
            source: "fixture_policy.md",
            section: "Opened electronics",
            text: "Opened electronics have a 15% restocking fee. <script>alert(1)</script>",
          },
        ],
      });
    return send({ detail: { code: "route_unavailable" } }, 404);
  })
  .listen(8108, "127.0.0.1");
