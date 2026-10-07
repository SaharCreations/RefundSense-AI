import { test, expect, Page } from "@playwright/test";
import fs from "node:fs";
const fixture = JSON.parse(
  fs.readFileSync(process.env.REFUNDGUARD_LIVE_FIXTURE!, "utf8"),
);
async function login(page: Page, role = "reviewer") {
  await page.goto("/");
  await page.getByLabel("User ID", { exact: true }).fill(fixture.users[role]);
  await page.getByLabel("Password", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Assess a refund." }),
  ).toBeVisible();
}
async function propose(page: Page, kind: string) {
  await page.getByLabel("Order ID", { exact: true }).fill(fixture.orders[kind]);
  await page
    .getByLabel("Customer ID", { exact: true })
    .fill(fixture.customer_id);
  await page.getByRole("button", { name: "Assess eligibility" }).click();
  await expect(page.getByText("$85.00", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Create approval request" }).click();
  await expect(
    page.getByRole("heading", { name: "Exact execution payload" }),
  ).toBeVisible();
  const wid = await page.getByLabel("Existing workflow ID").inputValue();
  const view = await page.evaluate(async (id) => {
    const r = await fetch(`/api/backend/workflows/${id}`);
    return r.json();
  }, wid);
  return view;
}
test("human-reviewed payload executes once, SQL audit persists, repeated decision is idempotent", async ({
  page,
}) => {
  await login(page);
  const view = await propose(page, "approve");
  await expect(
    page.getByRole("button", { name: "Approve and execute demo refund" }),
  ).toBeDisabled();
  await expect(page.getByTestId("execution-payload")).toContainText(
    view.exact_execution_payload.idempotency_key,
  );
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "Approve and execute demo refund" })
    .click();
  await expect(
    page.getByText("This workflow is executed.", { exact: false }),
  ).toBeVisible();
  const replay = await page.evaluate(
    async ({ id, hash }) => {
      const r = await fetch(`/api/backend/workflows/${id}/decisions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true, payload_sha256: hash }),
      });
      return { status: r.status, data: await r.json() };
    },
    { id: view.workflow_id, hash: view.payload_sha256 },
  );
  expect(replay.status).toBe(200);
  expect(replay.data.status).toBe("executed");
  await page.getByRole("button", { name: "View audit events" }).click();
  await expect(page.locator("pre").last()).toContainText("executed");
  await page.reload();
  await page.getByRole("button", { name: "Approval review" }).click();
  await page.getByLabel("Existing workflow ID").fill(view.workflow_id);
  await page.getByRole("button", { name: "Load workflow" }).click();
  await expect(
    page.getByText("This workflow is executed.", { exact: false }),
  ).toBeVisible();
});
test("support cannot approve even through a direct authenticated request", async ({
  page,
}) => {
  await login(page, "support");
  const view = await propose(page, "pending");
  await expect(
    page.getByRole("button", { name: "Approve and execute demo refund" }),
  ).toHaveCount(0);
  const status = await page.evaluate(
    async ({ id, hash }) =>
      (
        await fetch(`/api/backend/workflows/${id}/decisions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved: true, payload_sha256: hash }),
        })
      ).status,
    { id: view.workflow_id, hash: view.payload_sha256 },
  );
  expect(status).toBe(403);
});
test("reviewer rejects an exact pending request without a refund", async ({
  page,
}) => {
  await login(page);
  await propose(page, "reject");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Reject request" }).click();
  await expect(
    page.getByText("This workflow is rejected.", { exact: false }),
  ).toBeVisible();
});
test("different payload hash is rejected and pending request cannot execute through recovery", async ({
  page,
}) => {
  await login(page);
  const view = await propose(page, "stale");
  const result = await page.evaluate(async (id) => {
    const decision = await fetch(`/api/backend/workflows/${id}/decisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved: true, payload_sha256: "0".repeat(64) }),
    });
    const recovered = await fetch(`/api/backend/workflows/${id}/recover`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    return { decision: decision.status, recovered: await recovered.json() };
  }, view.workflow_id);
  expect(result.decision).toBe(409);
  expect(result.recovered.status).toBe("pending");
});
test("current dense policy evidence comes from the real pgvector index", async ({
  page,
}) => {
  test.skip(!fixture.with_retrieval, "Dense model not provided for this run");
  await login(page);
  await page.getByRole("button", { name: "Policy evidence" }).click();
  await page
    .getByLabel("Policy question")
    .fill("What is the opened electronics restocking fee?");
  await page.getByRole("button", { name: "Retrieve policy sections" }).click();
  await expect(page.locator("blockquote").first()).toBeVisible();
  await expect(page.locator(".citation")).toHaveCount(5);
  await expect(page.locator(".citation").first()).toContainText("15%");
});
if (process.env.REFUNDGUARD_RECORD_DEMO === "1")
  test("record real demo: SQL assessment, immutable pending payload, policy evidence", async ({
    browser,
  }) => {
    const output = process.env.REFUNDGUARD_DEMO_DIR!;
    const context = await browser.newContext({
      baseURL: process.env.REFUNDGUARD_LIVE_ORIGIN,
      viewport: { width: 1280, height: 900 },
      recordVideo: {
        dir: output + "/raw-video",
        size: { width: 1280, height: 900 },
      },
    });
    const page = await context.newPage();
    try {
      await page.goto("/");
      await page.waitForTimeout(1200);
      await login(page);
      await page.waitForTimeout(1200);
      await page
        .getByLabel("Order ID", { exact: true })
        .fill(fixture.orders.pending);
      await page.waitForTimeout(700);
      await page
        .getByLabel("Customer ID", { exact: true })
        .fill(fixture.customer_id);
      await page.waitForTimeout(700);
      await page.getByRole("button", { name: "Assess eligibility" }).click();
      await expect(page.getByText("$85.00", { exact: true })).toBeVisible();
      await page.waitForTimeout(2000);
      await page.screenshot({
        path: output + "/real-assessment.png",
        fullPage: true,
      });
      await page
        .getByRole("button", { name: "Create approval request" })
        .click();
      await expect(
        page.getByRole("heading", { name: "Exact execution payload" }),
      ).toBeVisible();
      await page.waitForTimeout(2200);
      await page.screenshot({
        path: output + "/real-review.png",
        fullPage: true,
      });
      await page.getByRole("checkbox").check();
      await expect(
        page.getByRole("button", { name: "Approve and execute demo refund" }),
      ).toBeEnabled();
      await page.waitForTimeout(1800);
      await page.getByRole("checkbox").uncheck();
      await expect(
        page.getByRole("button", { name: "Approve and execute demo refund" }),
      ).toBeDisabled();
      await page.getByRole("button", { name: "Policy evidence" }).click();
      await page
        .getByLabel("Policy question")
        .fill("What is the opened electronics restocking fee?");
      await page.waitForTimeout(1000);
      await page
        .getByRole("button", { name: "Retrieve policy sections" })
        .click();
      await expect(page.locator("blockquote").first()).toBeVisible();
      await page.waitForTimeout(2400);
      await page.screenshot({
        path: output + "/real-policy.png",
        fullPage: true,
      });
      await page.getByRole("button", { name: "Approval review" }).click();
      await expect(
        page.getByRole("button", { name: "Approve and execute demo refund" }),
      ).toBeDisabled();
      await page.waitForTimeout(2000);
    } finally {
      await context.close();
      await page.video()!.saveAs(output + "/demo.webm");
    }
  });
