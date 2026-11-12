// Thin fetch wrapper. Same-origin cookies, and the CSRF header the API requires on unsafe
// methods (portal/auth.py: X-Requested-With: portal; the browser adds Origin itself).
export const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function detailText(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((x) => {
        const e = x as { loc?: unknown[]; msg?: string };
        const where = (e.loc ?? []).slice(1).join(".");
        return where ? `${where}: ${e.msg ?? ""}` : (e.msg ?? "");
      })
      .join("; ");
  }
  return fallback;
}

export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  extraHeaders: Record<string, string> = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...extraHeaders };
  if (UNSAFE.has(method)) headers["X-Requested-With"] = "portal";
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path.startsWith("/api/") ? path : BASE + path, {
    method,
    credentials: "same-origin",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!res.ok) throw new ApiError(res.status, detailText(parsed, `Request failed (${res.status})`));
  return parsed as T;
}

export const get = <T>(path: string) => request<T>("GET", path);
export const post = <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
  request<T>("POST", path, body ?? {}, headers);
export const put = <T>(path: string, body: unknown) => request<T>("PUT", path, body);
export const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);

export const LOGIN_URL = "/api/auth/login";
