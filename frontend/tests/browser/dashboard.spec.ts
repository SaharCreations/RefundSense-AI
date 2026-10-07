import { test, expect, Page } from "@playwright/test";
async function signIn(page: Page, role = "reviewer") {
  await page.goto("/");
  await page.getByLabel("User ID", { exact: true }).fill(role);
  await page.getByLabel("Password", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Assess a refund." }),
  ).toBeVisible();
}
async function propose(page: Page) {
  await page.getByLabel("Order ID", { exact: true }).fill("ORD-1001");
  await page.getByLabel("Customer ID", { exact: true }).fill("CUS-1001");
  await page.getByRole("button", { name: "Assess eligibility" }).click();
  await expect(page.getByText("$85.00", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Create approval request" }).click();
  await expect(
    page.getByRole("heading", { name: "Exact execution payload" }),
  ).toBeVisible();
}
test.beforeEach(async ({ request }) => {
  await request.post("http://127.0.0.1:8108/test/reset");
});
test("reviewer approves only the exact displayed payload; receipt persists on reload", async ({
  page,
  request,
}) => {
  await signIn(page);
  await propose(page);
  const approve = page.getByRole("button", {
    name: "Approve and execute demo refund",
  });
  await expect(approve).toBeDisabled();
  await expect(page.getByTestId("execution-payload")).toContainText(
    '"original_payment_reference": "fixture-payment"',
  );
  await page.getByRole("checkbox").check();
  await expect(approve).toBeEnabled();
  await page.screenshot({
    path: "../reports/frontend_latest/review-desktop.png",
    fullPage: true,
  });
  await approve.click();
  await expect(
    page.getByText("fixture-ledger", { exact: false }),
  ).toBeVisible();
  expect(
    await (await request.get("http://127.0.0.1:8108/test/decisions")).json(),
  ).toEqual([{ approved: true, payload_sha256: "a".repeat(64) }]);
  await page.reload();
  await page.getByRole("button", { name: "Approval review" }).click();
  await page
    .getByLabel("Existing workflow ID")
    .fill("00000000-0000-4000-8000-000000000001");
  await page.getByRole("button", { name: "Load workflow" }).click();
  await expect(
    page.getByText("This workflow is executed.", { exact: false }),
  ).toBeVisible();
  await expect(approve).toHaveCount(0);
});
test("refresh clears confirmation; stale server state blocks execution", async ({
  page,
  request,
}) => {
  await signIn(page);
  await propose(page);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await page.getByRole("checkbox").check();
  await request.post("http://127.0.0.1:8108/test/stale");
  await page
    .getByRole("button", { name: "Approve and execute demo refund" })
    .click();
  await expect(
    page.getByRole("alert", { name: "Request error" }),
  ).toContainText("workflow changed");
  expect(
    await (await request.get("http://127.0.0.1:8108/test/decisions")).json(),
  ).toEqual([]);
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(
    page.getByText("This workflow is stale.", { exact: false }),
  ).toBeVisible();
});
test("support can assess and propose but sees no approval or audit controls", async ({
  page,
}) => {
  await signIn(page, "support");
  await propose(page);
  await expect(
    page.getByRole("button", { name: "Approve and execute demo refund" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "View audit events" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Only reviewer accounts", { exact: false }),
  ).toBeVisible();
});
test("IDs are exact and model abstention creates no workflow or decision", async ({
  page,
  request,
}) => {
  await signIn(page);
  await page.getByLabel("Order ID", { exact: true }).fill(" ORD-1001");
  await page.getByLabel("Customer ID", { exact: true }).fill("CUS-1001");
  await page.getByRole("button", { name: "Assess eligibility" }).click();
  await expect(
    page.getByRole("alert", { name: "Request error" }),
  ).toContainText("exact IDs");
  await page.getByLabel("Order ID", { exact: true }).fill("ORD-1001");
  await page.getByRole("button", { name: "Assess eligibility" }).click();
  await page
    .getByRole("button", { name: "Experimental AI explanation" })
    .click();
  await expect(
    page.getByText("The model abstained.", { exact: false }),
  ).toBeVisible();
  expect(
    await (await request.get("http://127.0.0.1:8108/test/decisions")).json(),
  ).toEqual([]);
});
test("policy evidence renders attacker markup as inert text", async ({
  page,
}) => {
  await signIn(page);
  await page.getByRole("button", { name: "Policy evidence" }).click();
  await page.getByLabel("Policy question").fill("Opened electronics fee?");
  await page.getByRole("button", { name: "Retrieve policy sections" }).click();
  await expect(page.locator("blockquote")).toContainText(
    "<script>alert(1)</script>",
  );
  await expect(page.locator("blockquote script")).toHaveCount(0);
});
test("mobile layout and secure session handling", async ({ page, context }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);
  const cookies = await context.cookies();
  expect(cookies.find((c) => c.name === "refundguard_session")).toMatchObject({
    httpOnly: true,
    sameSite: "Strict",
  });
  expect(
    await page.evaluate(() => ({
      local: localStorage.length,
      session: sessionStorage.length,
      cookie: document.cookie,
    })),
  ).toEqual({ local: 0, session: 0, cookie: "" });
  await propose(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../reports/frontend_latest/review-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("heading", { name: "Sign in to your workspace" }),
  ).toBeVisible();
  expect(
    (await context.cookies()).find((c) => c.name === "refundguard_session"),
  ).toBeUndefined();
});
test("reject binds to the same reviewed payload and never executes", async ({
  page,
  request,
}) => {
  await signIn(page);
  await propose(page);
  const reject = page.getByRole("button", { name: "Reject request" });
  await expect(reject).toBeDisabled();
  await page.getByRole("checkbox").check();
  await reject.click();
  await expect(
    page.getByText("This workflow is rejected.", { exact: false }),
  ).toBeVisible();
  expect(
    await (await request.get("http://127.0.0.1:8108/test/decisions")).json(),
  ).toEqual([{ approved: false, payload_sha256: "a".repeat(64) }]);
  await expect(page.getByText("fixture-ledger", { exact: false })).toHaveCount(
    0,
  );
});
