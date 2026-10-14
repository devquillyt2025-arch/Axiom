/** Typed fetch wrapper for the Axiom FastAPI backend. */

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const LOGIN_URL = `${API_BASE}/auth/login`;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
  get authRequired() {
    return this.status === 401 || this.code === "auth_required";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      cache: "no-store",
      ...init,
      headers: {
        "Content-Type": "application/json",
        // Required by the API on every state-changing call (CSRF guard); harmless on GETs.
        "X-Axiom": "1",
        ...(init.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError(0, `Can't reach the Axiom API at ${API_BASE}. Is the backend running?`, "unreachable");
  }
  if (!res.ok) {
    let detail = res.statusText;
    let code: string | undefined;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
      code = body.code;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail, code);
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
};

/** Tell the Logs tab about something only the browser knows (a tab opened, a file exported). Never throws. */
export function logEvent(category: "navigation" | "reports" | "backtest", action: string, summary: string, details?: Record<string, unknown>) {
  void request("/logs/event", { method: "POST", body: JSON.stringify({ category, action, summary, details }) }).catch(() => {});
}

export const fetcher = <T>(path: string) => api.get<T>(path);

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
