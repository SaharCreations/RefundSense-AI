import { test } from "node:test";
import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { POST, GET } from "../app/api/backend/[...path]/route";
const origin = "http://localhost:3000";
const context = (path: string) => ({
  params: Promise.resolve({ path: path.split("/") }),
});
function request(
  path: string,
  method = "POST",
  body: unknown = {},
  headers: Record<string, string> = {},
) {
  return new NextRequest(`${origin}/api/backend/${path}`, {
    method,
    headers: { origin, "Content-Type": "application/json", ...headers },
    ...(method === "POST" ? { body: JSON.stringify(body) } : {}),
  });
}
test("proxy rejects CSRF and anonymous decisions before contacting backend", async () => {
  const original = global.fetch;
  global.fetch = async () => {
    throw Error("must not fetch");
  };
  try {
    assert.equal(
      (
        await POST(
          request("workflows", "POST", {}, { origin: "https://evil.example" }),
          context("workflows"),
        )
      ).status,
      403,
    );
    assert.equal(
      (await POST(request("workflows"), context("workflows"))).status,
      401,
    );
    assert.equal(
      (await GET(request("arbitrary", "GET"), context("arbitrary"))).status,
      404,
    );
  } finally {
    global.fetch = original;
  }
});
test("login response never exposes bearer token, cookie is HttpOnly and strict", async () => {
  const original = global.fetch;
  global.fetch = async () =>
    Response.json({ access_token: "opaque-backend-token", expires_in: 28800 });
  try {
    const response = await POST(
      request("auth/login", "POST", { user_id: "alice", password: "test" }),
      context("auth/login"),
    );
    assert.deepEqual(await response.json(), { authenticated: true });
    assert.match(response.headers.get("set-cookie")!, /HttpOnly/);
    assert.match(response.headers.get("set-cookie")!, /SameSite=strict/i);
    assert.equal(response.headers.get("cache-control"), "no-store");
  } finally {
    global.fetch = original;
  }
});
test("cookie supplies backend identity; browser Authorization and redirects do not", async () => {
  const original = global.fetch;
  global.fetch = async (url, options) => {
    assert.equal(String(url), "http://127.0.0.1:8000/api/v1/auth/me");
    assert.equal(
      (options?.headers as Record<string, string>).Authorization,
      "Bearer trusted-cookie",
    );
    assert.equal(options?.redirect, "error");
    return Response.json({ user_id: "reviewer" });
  };
  try {
    const response = await GET(
      request(
        "auth/me",
        "GET",
        {},
        {
          cookie: "refundguard_session=trusted-cookie",
          Authorization: "Bearer attacker",
        },
      ),
      context("auth/me"),
    );
    assert.equal(response.status, 200);
  } finally {
    global.fetch = original;
  }
});
test("expired SQL session clears the browser cookie", async () => {
  const original = global.fetch;
  global.fetch = async () =>
    Response.json({ detail: { code: "invalid_session" } }, { status: 401 });
  try {
    const response = await GET(
      request("auth/me", "GET", {}, { cookie: "refundguard_session=expired" }),
      context("auth/me"),
    );
    assert.equal(response.status, 401);
    assert.match(response.headers.get("set-cookie")!, /Max-Age=0/);
  } finally {
    global.fetch = original;
  }
});
test("request size limit covers bodies without Content-Length", async () => {
  const response = await POST(
    request("auth/login", "POST", { password: "x".repeat(33000) }),
    context("auth/login"),
  );
  assert.equal(response.status, 413);
});
test("development Host origin survives Next URL normalization", async () => {
  const original = global.fetch;
  global.fetch = async () =>
    Response.json({ access_token: "opaque", expires_in: 100 });
  try {
    const response = await POST(
      request(
        "auth/login",
        "POST",
        { user_id: "alice", password: "test" },
        { host: "127.0.0.1:3000", origin: "http://127.0.0.1:3000" },
      ),
      context("auth/login"),
    );
    assert.equal(response.status, 200);
  } finally {
    global.fetch = original;
  }
});
test("production requires a fixed HTTPS origin and uses Secure session cookies", async () => {
  const originalFetch = global.fetch;
  const priorMode = process.env.NODE_ENV;
  const priorOrigin = process.env.REFUNDGUARD_WEB_ORIGIN;
  Object.assign(process.env, { NODE_ENV: "production" });
  delete process.env.REFUNDGUARD_WEB_ORIGIN;
  global.fetch = async () =>
    Response.json({ access_token: "opaque", expires_in: 36000 });
  try {
    assert.equal(
      (await POST(request("auth/login"), context("auth/login"))).status,
      503,
    );
    process.env.REFUNDGUARD_WEB_ORIGIN = "http://review.example";
    assert.equal(
      (await POST(request("auth/login"), context("auth/login"))).status,
      503,
    );
    process.env.REFUNDGUARD_WEB_ORIGIN = "https://review.example";
    const response = await POST(
      request("auth/login", "POST", {}, { origin: "https://review.example" }),
      context("auth/login"),
    );
    assert.equal(response.status, 200);
    assert.match(response.headers.get("set-cookie")!, /Secure/);
    assert.match(response.headers.get("set-cookie")!, /Max-Age=28800/);
  } finally {
    global.fetch = originalFetch;
    if (priorMode === undefined)
      Reflect.deleteProperty(process.env, "NODE_ENV");
    else Object.assign(process.env, { NODE_ENV: priorMode });
    if (priorOrigin === undefined) delete process.env.REFUNDGUARD_WEB_ORIGIN;
    else process.env.REFUNDGUARD_WEB_ORIGIN = priorOrigin;
  }
});
