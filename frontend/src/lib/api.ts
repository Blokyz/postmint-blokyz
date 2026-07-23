// Centralized API client for the backend. Replaces the copy-pasted
// `const API_URL = ... ?? "http://localhost:8000"` + inline fetch/error handling
// that was duplicated across every page. New pages (Phases 3–4) use these helpers.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const ADDRESS_RE = /^0x[a-fA-F0-9]{40}$/;

// A backend error carrying the FastAPI `detail` (string OR object — our claim
// endpoints return structured details). `.message` is a human line; `.detail`
// keeps the raw payload for callers that want to branch on it.
export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, fallback: string) {
    super(typeof detail === "string" ? detail : fallback);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function parse<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? null, `${fallback} (${res.status})`);
  }
  return (await res.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return fetch(`${API_URL}${path}`).then((r) => parse<T>(r, "Request failed"));
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => parse<T>(r, "Request failed"));
}

export function shortAddr(a: string): string {
  return `${a.slice(0, 6)}…${a.slice(-4)}`;
}
