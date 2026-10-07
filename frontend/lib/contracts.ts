export type Identity = {
  user_id: string;
  organization_id: string;
  role: "support" | "reviewer";
};
export type OrderInput = {
  order_id: string;
  customer_id: string;
  reason: "standard_return" | "damaged_on_arrival" | "warranty";
};
export type Citation = {
  source: string;
  section: string;
  quote?: string;
  content?: string;
  text?: string;
  version?: string;
  source_sha256?: string;
  line_start?: number;
  line_end?: number;
  [key: string]: unknown;
};
export type Assessment = {
  decision: "eligible" | "ineligible" | "review";
  reason_code: string;
  refund_amount_minor: number | null;
  restocking_fee_minor: number | null;
  currency: string;
  rules_version: string;
  citations: Citation[];
  snapshot: Record<string, unknown>;
};
export type Workflow = {
  workflow_id: string;
  status:
    | "pending"
    | "approved"
    | "rejected"
    | "expired"
    | "stale"
    | "executed";
  exact_execution_payload: {
    execution_target: "demo_ledger";
    idempotency_key: string;
    refund: {
      order_id: string;
      customer_id: string;
      refund_amount_minor: number;
      restocking_fee_minor: number;
      currency: string;
      [key: string]: unknown;
    };
  };
  payload_sha256: string;
  approval_ttl_seconds: number;
  expires_at: string | null;
  assessment: Assessment;
  result: Record<string, unknown> | null;
  demo_only: boolean;
};
export type Explanation = {
  status: "answered" | "abstain";
  explanation: string;
  citations: Citation[];
  abstention_reason: string | null;
  execution_allowed: false;
};
export function exactId(value: string): boolean {
  return (
    value.length > 0 &&
    value.length <= 64 &&
    value === value.trim() &&
    !/\p{C}/u.test(value)
  );
}
export function exactWorkflowId(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    value,
  );
}
export function canDecide(
  user: Identity,
  workflow: Workflow,
  reviewedHash: string | null,
  busy: boolean,
  now: number,
): boolean {
  return (
    user.role === "reviewer" &&
    workflow.status === "pending" &&
    !busy &&
    reviewedHash === workflow.payload_sha256 &&
    /^[0-9a-f]{64}$/.test(workflow.payload_sha256) &&
    (workflow.expires_at === null || Date.parse(workflow.expires_at) > now)
  );
}
export function money(amount: number | null, currency: string): string {
  return amount === null
    ? "Awaiting review"
    : new Intl.NumberFormat("en-US", { style: "currency", currency }).format(
        amount / 100,
      );
}
