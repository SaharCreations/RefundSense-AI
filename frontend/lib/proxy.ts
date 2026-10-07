// Allowlist the existing FastAPI contracts; never accept an arbitrary upstream URL.
export function allowedPath(parts: string[], method: string): boolean {
  const path = parts.join("/");
  if (method === "GET")
    return (
      path === "auth/me" || /^workflows\/[0-9a-f-]{36}(\/audit)?$/i.test(path)
    );
  if (method !== "POST") return false;
  return (
    [
      "auth/login",
      "auth/logout",
      "assessments",
      "assessments/explain",
      "workflows",
      "policy/search",
      "policy/answer",
    ].includes(path) ||
    /^workflows\/[0-9a-f-]{36}\/(decisions|recover)$/i.test(path)
  );
}
export function trustedOrigin(
  origin: string | null,
  expected: string,
): boolean {
  return origin !== null && origin === expected;
}
