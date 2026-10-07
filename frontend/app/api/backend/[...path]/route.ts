import { NextRequest, NextResponse } from "next/server";
import { allowedPath, trustedOrigin } from "@/lib/proxy";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const cookie = "refundguard_session";
const headers = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};
const failure = (code: string, status: number) =>
  NextResponse.json({ detail: { code } }, { status, headers });
async function handle(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  if (!allowedPath(path, request.method) || request.nextUrl.search)
    return failure("route_unavailable", 404);
  const configuredOrigin = process.env.REFUNDGUARD_WEB_ORIGIN;
  if (process.env.NODE_ENV === "production" && !configuredOrigin)
    return failure("backend_configuration", 503);
  if (configuredOrigin) {
    try {
      const publicUrl = new URL(configuredOrigin);
      if (
        publicUrl.origin !== configuredOrigin ||
        (process.env.NODE_ENV === "production" &&
          publicUrl.protocol !== "https:")
      )
        throw Error();
    } catch {
      return failure("backend_configuration", 503);
    }
  }
  // Next may normalize the request URL to localhost in development. Browser Host retains the actual origin.
  const expected =
    configuredOrigin ||
    `${request.nextUrl.protocol}//${request.headers.get("host") || request.nextUrl.host}`;
  if (
    request.method === "POST" &&
    !trustedOrigin(request.headers.get("origin"), expected)
  )
    return failure("origin_rejected", 403);
  let base: URL;
  try {
    base = new URL(process.env.REFUNDGUARD_API_URL || "http://127.0.0.1:8000");
    if (
      !["http:", "https:"].includes(base.protocol) ||
      base.username ||
      base.password ||
      base.search ||
      base.hash ||
      base.pathname !== "/"
    )
      throw Error();
  } catch {
    return failure("backend_configuration", 503);
  }
  const isLogin = path.join("/") === "auth/login",
    isLogout = path.join("/") === "auth/logout";
  const token = request.cookies.get(cookie)?.value;
  if (!isLogin && !token) return failure("authentication_required", 401);
  let body: string | undefined;
  if (request.method === "POST") {
    if (!request.headers.get("content-type")?.startsWith("application/json"))
      return failure("json_required", 415);
    // Enforce an actual stream limit, including requests without Content-Length.
    const reader = request.body?.getReader();
    let bytes = 0;
    const pieces: Uint8Array[] = [];
    if (reader) {
      while (true) {
        const item = await reader.read();
        if (item.done) break;
        bytes += item.value.length;
        if (bytes > 32768) {
          await reader.cancel();
          return failure("request_too_large", 413);
        }
        pieces.push(item.value);
      }
    }
    try {
      body = Buffer.concat(pieces).toString("utf8");
      JSON.parse(body);
    } catch {
      return failure("invalid_json", 400);
    }
  }
  try {
    const response = await fetch(new URL(`/api/v1/${path.join("/")}`, base), {
      method: request.method,
      headers: {
        "Content-Type": "application/json",
        ...(token && !isLogin ? { Authorization: `Bearer ${token}` } : {}),
      },
      body,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(120000),
    });
    let result: NextResponse;
    if (isLogin && response.ok) {
      const data = await response.json();
      if (
        typeof data.access_token !== "string" ||
        !Number.isInteger(data.expires_in) ||
        data.expires_in <= 0
      )
        return failure("invalid_backend_response", 502);
      result = NextResponse.json({ authenticated: true }, { headers });
      result.cookies.set(cookie, data.access_token, {
        httpOnly: true,
        sameSite: "strict",
        secure: process.env.NODE_ENV === "production",
        path: "/",
        maxAge: Math.min(data.expires_in, 28800),
      });
    } else {
      result = new NextResponse(
        response.status === 204 ? null : await response.text(),
        {
          status: response.status,
          headers: {
            ...headers,
            "Content-Type": "application/json",
            ...(response.headers.get("retry-after")
              ? { "Retry-After": response.headers.get("retry-after")! }
              : {}),
          },
        },
      );
    }
    if (isLogout || (!isLogin && response.status === 401))
      result.cookies.set(cookie, "", {
        httpOnly: true,
        sameSite: "strict",
        secure: process.env.NODE_ENV === "production",
        path: "/",
        maxAge: 0,
      });
    return result;
  } catch {
    return failure("backend_unavailable", 503);
  }
}
export { handle as GET, handle as POST };
