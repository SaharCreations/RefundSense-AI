"use client";
import { useEffect, useRef, useState } from "react";
import {
  Assessment,
  Citation,
  Explanation,
  Identity,
  OrderInput,
  Workflow,
  canDecide,
  exactId,
  exactWorkflowId,
  money,
} from "@/lib/contracts";
const messages: Record<string, string> = {
  invalid_credentials: "The user ID or password is incorrect.",
  login_limited: "Too many attempts. Try again in 15 minutes.",
  record_unavailable: "No accessible record matches these exact IDs.",
  workflow_conflict:
    "The workflow changed or cannot be resumed. Refresh its status.",
  reviewer_required: "A reviewer account is required.",
  database_unavailable: "The database is unavailable.",
  backend_unavailable:
    "The API is unavailable or timed out. Refresh workflow status before retrying an action.",
  authentication_required: "Sign in to continue.",
  invalid_session: "Your session ended. Sign in again.",
  validation_failed: "Check the exact IDs and required fields.",
  explanation_unavailable:
    "The experimental explanation model is not configured.",
  retrieval_unavailable: "Policy retrieval is not configured.",
};
function Evidence({ items }: { items: Citation[] }) {
  return (
    <div className="evidence">
      {items.length === 0 ? (
        <p className="muted">No citations returned.</p>
      ) : (
        items.map((c, i) => (
          <article className="citation" key={i}>
            <span className="eyebrow">SOURCE {i + 1}</span>
            <strong>{c.section}</strong>
            <small>
              {c.source}
              {c.version ? ` · ${c.version}` : ""}
              {c.line_start ? ` · lines ${c.line_start}–${c.line_end}` : ""}
            </small>
            {(c.quote || c.content || c.text) && (
              <blockquote>{c.quote || c.content || c.text}</blockquote>
            )}
          </article>
        ))
      )}
    </div>
  );
}
function AssessmentCard({ value }: { value: Assessment }) {
  return (
    <>
      <div className="outcome">
        <span className={`badge ${value.decision}`}>{value.decision}</span>
        <span className="muted">Deterministic Python assessment</span>
      </div>
      <div className="amounts">
        <div>
          <small>Refund</small>
          <strong>{money(value.refund_amount_minor, value.currency)}</strong>
        </div>
        <div>
          <small>Restocking fee</small>
          <strong>{money(value.restocking_fee_minor, value.currency)}</strong>
        </div>
      </div>
      <p className="reason">{value.reason_code.replaceAll("_", " ")}</p>
      <small className="muted">
        Rules: {value.rules_version} · Assessment only
      </small>
      <h3>Policy basis</h3>
      <Evidence items={value.citations} />
    </>
  );
}
export default function Dashboard() {
  const inFlight = useRef(false);
  const [user, setUser] = useState<Identity | null>(null),
    [boot, setBoot] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [tab, setTab] = useState<"assess" | "review" | "policy">("assess");
  const [login, setLogin] = useState({ user_id: "", password: "" });
  const [order, setOrder] = useState<OrderInput>({
    order_id: "",
    customer_id: "",
    reason: "standard_return",
  });
  const [assessment, setAssessment] = useState<Assessment | null>(null),
    [explanation, setExplanation] = useState<Explanation | null>(null);
  const [workflow, setWorkflow] = useState<Workflow | null>(null),
    [lookup, setLookup] = useState(""),
    [reviewed, setReviewed] = useState<string | null>(null),
    [audit, setAudit] = useState<unknown>(null);
  const [question, setQuestion] = useState(""),
    [evidence, setEvidence] = useState<Citation[] | null>(null),
    [scopeDate, setScopeDate] = useState("");
  const [now, setNow] = useState(Date.now());
  function clearSession() {
    setUser(null);
    setLogin({ user_id: "", password: "" });
    setAssessment(null);
    setExplanation(null);
    setWorkflow(null);
    setReviewed(null);
    setAudit(null);
    setEvidence(null);
    setOrder({ order_id: "", customer_id: "", reason: "standard_return" });
    setLookup("");
    setQuestion("");
  }
  async function api(path: string, body?: unknown) {
    const response = await fetch(`/api/backend/${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      cache: "no-store",
    });
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) {
      if (response.status === 401 && path !== "auth/login") clearSession();
      throw Error(
        messages[data?.detail?.code] ||
          `Request failed (${response.status}). Check the API configuration or refresh the workflow.`,
      );
    }
    return data;
  }
  async function run(action: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  useEffect(() => {
    let active = true;
    fetch("/api/backend/auth/me", { cache: "no-store" })
      .then(async (r) => {
        if (r.ok) {
          const data = await r.json();
          if (active) setUser(data);
        } else if (r.status !== 401 && active)
          setError(
            "Cannot connect to the API. Check that the backend is running.",
          );
      })
      .catch(() => {
        if (active) setError("Cannot connect to the API.");
      })
      .finally(() => {
        if (active) setBoot(false);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  function acceptWorkflow(value: Workflow) {
    setWorkflow(value);
    setLookup(value.workflow_id);
    setReviewed(null);
    setAudit(null);
    setTab("review");
  }
  function validatedOrder() {
    if (!exactId(order.order_id) || !exactId(order.customer_id))
      throw Error(
        "Enter both exact IDs without surrounding whitespace or control characters.",
      );
    return { ...order };
  }
  const ready =
    !!user && !!workflow && canDecide(user, workflow, reviewed, busy, now);
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="mark">R</span>
          <span>
            RefundSense<small>REVIEW WORKSPACE</small>
          </span>
        </div>
        <div className="side-label">WORKSPACE</div>
        <nav aria-label="Workspace">
          {(
            [
              ["assess", "01", "Assess a refund"],
              ["review", "02", "Approval review"],
              ["policy", "03", "Policy evidence"],
            ] as const
          ).map(([key, num, label]) => (
            <button
              key={key}
              disabled={!user || busy}
              aria-current={tab === key ? "page" : undefined}
              onClick={() => {
                setTab(key);
                setError("");
              }}
            >
              <span aria-hidden="true">{num}</span>
              {label}
            </button>
          ))}
        </nav>
        <div className="side-bottom">
          <span className="live-dot" /> PORTFOLIO DEMO
          <p>
            Deterministic decisions.
            <br />
            Human-controlled actions.
          </p>
          <small>Execution target: synthetic ledger</small>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <span className="eyebrow">REFUND OPERATIONS</span>
            <h1>
              {!user
                ? "Review with confidence."
                : tab === "assess"
                  ? "Assess a refund."
                  : tab === "review"
                    ? "Review before execution."
                    : "Find the policy basis."}
            </h1>
            <p className="muted">
              Company policy as evidence. Python rules as the decision maker.
            </p>
          </div>
          {user && (
            <div className="account">
              <span className="badge">{user.role}</span>
              <strong>{user.user_id}</strong>
              <small>{user.organization_id}</small>
              <button
                className="text-button"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await api("auth/logout", {});
                    clearSession();
                  })
                }
              >
                Sign out
              </button>
            </div>
          )}
        </header>
        {error && (
          <div className="alert" role="alert" aria-label="Request error">
            {error}
          </div>
        )}
        {boot ? (
          <section className="panel">
            <p>Checking your session…</p>
          </section>
        ) : !user ? (
          <section className="panel signin">
            <span className="eyebrow">TRUSTED ACCOUNT ACCESS</span>
            <h2>Sign in to your workspace</h2>
            <p className="muted">
              Use an account created by your administrator.
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                run(async () => {
                  if (!exactId(login.user_id))
                    throw Error("Enter an exact user ID.");
                  await api("auth/login", login);
                  setLogin({ user_id: "", password: "" });
                  setUser(await api("auth/me"));
                });
              }}
            >
              <label>
                User ID
                <input
                  autoComplete="username"
                  required
                  value={login.user_id}
                  disabled={busy}
                  onChange={(e) =>
                    setLogin({ ...login, user_id: e.target.value })
                  }
                />
              </label>
              <label>
                Password
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  value={login.password}
                  disabled={busy}
                  onChange={(e) =>
                    setLogin({ ...login, password: e.target.value })
                  }
                />
              </label>
              <button className="primary" disabled={busy}>
                {busy ? "Signing in…" : "Sign in"}
                <span aria-hidden="true">→</span>
              </button>
            </form>
          </section>
        ) : (
          <>
            {tab === "assess" && (
              <div className="grid">
                <section className="panel">
                  <span className="eyebrow">01 / RECORD LOOKUP</span>
                  <h2>Start with exact IDs</h2>
                  <p className="muted">
                    Customer and order records come directly from SQL.
                  </p>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      run(async () => {
                        const input = validatedOrder();
                        setAssessment(null);
                        setExplanation(null);
                        setAssessment(await api("assessments", input));
                      });
                    }}
                  >
                    <label>
                      Order ID
                      <input
                        required
                        maxLength={64}
                        value={order.order_id}
                        disabled={busy}
                        placeholder="Enter the exact order ID"
                        onChange={(e) => {
                          setOrder({ ...order, order_id: e.target.value });
                          setAssessment(null);
                          setExplanation(null);
                        }}
                      />
                    </label>
                    <label>
                      Customer ID
                      <input
                        required
                        maxLength={64}
                        value={order.customer_id}
                        disabled={busy}
                        placeholder="Enter the exact customer ID"
                        onChange={(e) => {
                          setOrder({ ...order, customer_id: e.target.value });
                          setAssessment(null);
                          setExplanation(null);
                        }}
                      />
                    </label>
                    <label>
                      Reason
                      <select
                        value={order.reason}
                        disabled={busy}
                        onChange={(e) => {
                          setOrder({
                            ...order,
                            reason: e.target.value as OrderInput["reason"],
                          });
                          setAssessment(null);
                          setExplanation(null);
                        }}
                      >
                        <option value="standard_return">Standard return</option>
                        <option value="damaged_on_arrival">
                          Damaged on arrival
                        </option>
                        <option value="warranty">Warranty</option>
                      </select>
                    </label>
                    <button className="primary" disabled={busy}>
                      {busy ? "Working…" : "Assess eligibility"}
                      <span aria-hidden="true">→</span>
                    </button>
                  </form>
                  <div className="note">
                    Eligibility, dates, fees, and refund amounts are calculated
                    by deterministic code.
                  </div>
                </section>
                <section className="panel result">
                  <span className="eyebrow">02 / RULES RESULT</span>
                  {assessment ? (
                    <>
                      <AssessmentCard value={assessment} />
                      <div className="actions">
                        <button
                          className="primary"
                          disabled={busy || assessment.decision !== "eligible"}
                          onClick={() =>
                            run(async () => {
                              const value = await api(
                                "workflows",
                                validatedOrder(),
                              );
                              if (value.status === "assessment_blocked") {
                                setAssessment(value.assessment);
                                throw Error(
                                  "The live assessment blocks this action. Review the updated result.",
                                );
                              }
                              acceptWorkflow(value);
                            })
                          }
                        >
                          Create approval request →
                        </button>
                        <button
                          className="secondary"
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              setExplanation(null);
                              const value = await api(
                                "assessments/explain",
                                validatedOrder(),
                              );
                              setAssessment(value.authoritative_assessment);
                              setExplanation(value.policy_explanation);
                            })
                          }
                        >
                          Experimental AI explanation
                        </button>
                      </div>
                      {explanation && (
                        <div className="experimental">
                          <span className="eyebrow">
                            EXPERIMENTAL · REFERENCE ONLY
                          </span>
                          <p>
                            {explanation.status === "abstain"
                              ? "The model abstained. Use the deterministic result and review the cited policy."
                              : explanation.explanation}
                          </p>
                          <Evidence items={explanation.citations} />
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="empty">
                      <span className="empty-icon">✓</span>
                      <h2>A clear decision starts here.</h2>
                      <p>
                        Assess a record to see the amount,
                        <br />
                        rules, and supporting policy sections.
                      </p>
                    </div>
                  )}
                </section>
              </div>
            )}
            {tab === "review" && (
              <>
                <section className="panel lookup">
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      run(async () => {
                        if (!exactWorkflowId(lookup))
                          throw Error("Enter the exact workflow UUID.");
                        setWorkflow(null);
                        setReviewed(null);
                        setAudit(null);
                        acceptWorkflow(await api(`workflows/${lookup}`));
                      });
                    }}
                  >
                    <label>
                      Existing workflow ID
                      <input
                        value={lookup}
                        disabled={busy}
                        placeholder="Paste the exact workflow UUID"
                        required
                        onChange={(e) => {
                          setLookup(e.target.value);
                          setWorkflow(null);
                          setReviewed(null);
                          setAudit(null);
                        }}
                      />
                    </label>
                    <button className="secondary" disabled={busy}>
                      Load workflow
                    </button>
                  </form>
                </section>
                {workflow ? (
                  <div className="grid review-grid">
                    <section className="panel">
                      <div className="outcome">
                        <span className={`badge ${workflow.status}`}>
                          {workflow.status}
                        </span>
                        <span className="muted">Synthetic ledger only</span>
                      </div>
                      <h2>Exact execution payload</h2>
                      <p className="muted">
                        Review every field. This server-generated payload is
                        immutable.
                      </p>
                      <pre data-testid="execution-payload">
                        {JSON.stringify(
                          workflow.exact_execution_payload,
                          null,
                          2,
                        )}
                      </pre>
                      <div className="hash">
                        <small>PAYLOAD SHA-256</small>
                        <code>{workflow.payload_sha256}</code>
                      </div>
                      <small className="muted">
                        Workflow ID: {workflow.workflow_id}
                      </small>
                    </section>
                    <section className="panel">
                      <span className="eyebrow">HUMAN APPROVAL</span>
                      <h2>
                        {money(
                          workflow.exact_execution_payload.refund
                            .refund_amount_minor,
                          workflow.exact_execution_payload.refund.currency,
                        )}{" "}
                        refund
                      </h2>
                      <p className="muted">
                        {workflow.exact_execution_payload.refund.order_id} ·{" "}
                        {workflow.exact_execution_payload.refund.customer_id}
                      </p>
                      <div className="note">
                        Approval validity: {workflow.approval_ttl_seconds / 60}{" "}
                        minutes after approval is granted. Live order state is
                        revalidated before execution.
                      </div>
                      {workflow.expires_at && (
                        <p className="muted">
                          Approval expires:{" "}
                          {new Date(workflow.expires_at).toLocaleString()}
                        </p>
                      )}
                      {user.role === "reviewer" &&
                      workflow.status === "pending" ? (
                        <>
                          <label className="check">
                            <input
                              type="checkbox"
                              disabled={busy}
                              checked={reviewed === workflow.payload_sha256}
                              onChange={(e) =>
                                setReviewed(
                                  e.target.checked
                                    ? workflow.payload_sha256
                                    : null,
                                )
                              }
                            />
                            <span>
                              I reviewed the exact payload, amount, payment
                              reference, and idempotency key.
                            </span>
                          </label>
                          <div className="actions">
                            <button
                              className="primary"
                              disabled={!ready}
                              onClick={() =>
                                run(async () => {
                                  setReviewed(null);
                                  acceptWorkflow(
                                    await api(
                                      `workflows/${workflow.workflow_id}/decisions`,
                                      {
                                        approved: true,
                                        payload_sha256: workflow.payload_sha256,
                                      },
                                    ),
                                  );
                                })
                              }
                            >
                              Approve and execute demo refund
                            </button>
                            <button
                              className="danger"
                              disabled={!ready}
                              onClick={() =>
                                run(async () => {
                                  setReviewed(null);
                                  acceptWorkflow(
                                    await api(
                                      `workflows/${workflow.workflow_id}/decisions`,
                                      {
                                        approved: false,
                                        payload_sha256: workflow.payload_sha256,
                                      },
                                    ),
                                  );
                                })
                              }
                            >
                              Reject request
                            </button>
                          </div>
                        </>
                      ) : user.role === "support" ? (
                        <p className="note">
                          Only reviewer accounts can approve, reject, recover,
                          or view audit events.
                        </p>
                      ) : (
                        <p className="note">
                          This workflow is {workflow.status}. Refresh to check
                          its latest server state.
                        </p>
                      )}
                      <div className="actions">
                        <button
                          className="secondary"
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              setReviewed(null);
                              acceptWorkflow(
                                await api(`workflows/${workflow.workflow_id}`),
                              );
                            })
                          }
                        >
                          Refresh status
                        </button>
                        {user.role === "reviewer" &&
                          workflow.status === "approved" && (
                            <button
                              className="secondary"
                              disabled={busy}
                              onClick={() =>
                                run(async () => {
                                  setReviewed(null);
                                  acceptWorkflow(
                                    await api(
                                      `workflows/${workflow.workflow_id}/recover`,
                                      {},
                                    ),
                                  );
                                })
                              }
                            >
                              Recover approved workflow
                            </button>
                          )}
                        {user.role === "reviewer" && (
                          <button
                            className="text-button"
                            disabled={busy}
                            onClick={() =>
                              run(async () => {
                                setAudit(
                                  await api(
                                    `workflows/${workflow.workflow_id}/audit`,
                                  ),
                                );
                              })
                            }
                          >
                            View audit events
                          </button>
                        )}
                      </div>
                      {workflow.result && (
                        <>
                          <h3>Execution result</h3>
                          <pre>{JSON.stringify(workflow.result, null, 2)}</pre>
                        </>
                      )}
                      {audit !== null && (
                        <>
                          <h3>Audit events</h3>
                          <pre>{JSON.stringify(audit, null, 2)}</pre>
                        </>
                      )}
                    </section>
                  </div>
                ) : (
                  <section className="panel empty">
                    <h2>No workflow selected</h2>
                    <p>
                      Create an approval request from an eligible assessment,
                      <br />
                      or load a saved workflow using its exact UUID.
                    </p>
                  </section>
                )}
              </>
            )}
            {tab === "policy" && (
              <div className="grid">
                <section className="panel">
                  <span className="eyebrow">DENSE RETRIEVAL</span>
                  <h2>Search current policy</h2>
                  <p className="muted">
                    Retrieved sections are reference evidence. They do not
                    determine eligibility or authorize actions.
                  </p>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      run(async () => {
                        setEvidence(null);
                        const value = await api("policy/search", {
                          question,
                          k: 5,
                        });
                        setEvidence(value.retrieved);
                        setScopeDate(value.as_of);
                      });
                    }}
                  >
                    <label>
                      Policy question
                      <textarea
                        required
                        maxLength={2000}
                        value={question}
                        disabled={busy}
                        rows={5}
                        placeholder="What is the restocking fee for opened electronics?"
                        onChange={(e) => {
                          setQuestion(e.target.value);
                          setEvidence(null);
                        }}
                      />
                    </label>
                    <button
                      className="primary"
                      disabled={busy || !question.trim()}
                    >
                      Retrieve policy sections →
                    </button>
                  </form>
                  <div className="note">
                    Current policies only · Top 5 dense matches
                  </div>
                </section>
                <section className="panel">
                  <span className="eyebrow">SOURCE EVIDENCE</span>
                  <h2>Retrieved sections</h2>
                  {evidence ? (
                    <>
                      <p className="muted">
                        Policy date: {scopeDate} · Ranked by similarity
                      </p>
                      <Evidence items={evidence} />
                    </>
                  ) : (
                    <p className="muted">
                      Enter a question to inspect cited source sections.
                    </p>
                  )}
                </section>
              </div>
            )}
          </>
        )}
        <footer>
          <span>RefundSense AI</span>
          <span>
            Policy evidence → deterministic assessment → human approval
          </span>
        </footer>
      </main>
    </div>
  );
}
