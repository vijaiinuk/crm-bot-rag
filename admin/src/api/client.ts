// Thin fetch wrapper for the admin API. The token is attached here and nowhere else.

export class ApiError extends Error {
  readonly status: number;
  readonly details: string[];

  constructor(status: number, details: string[]) {
    super(details[0] ?? `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export interface Api {
  base: string;
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
  put<T>(path: string, body: unknown): Promise<T>;
  patch<T>(path: string, body: unknown): Promise<T>;
  del<T>(path: string): Promise<T>;
  upload<T>(path: string, file: File): Promise<T>;
}

/** FastAPI errors: {detail: string} or {detail: string[]} or {detail: [{msg, loc}]}. */
async function errorDetails(res: Response): Promise<string[]> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    const d = body.detail;
    if (typeof d === "string") return [d];
    if (Array.isArray(d)) {
      return d.map((x) =>
        typeof x === "string" ? x : typeof x === "object" && x && "msg" in x ? String((x as { msg: unknown }).msg) : JSON.stringify(x),
      );
    }
  } catch {
    /* not JSON */
  }
  return [res.statusText || `HTTP ${res.status}`];
}

export function createApi(
  base: string,
  getToken: () => string | null,
  onUnauthorized: () => void,
  fetchImpl: typeof fetch = (...args) => fetch(...args),
): Api {
  const root = base.replace(/\/$/, "");

  async function request<T>(method: string, path: string, body?: BodyInit, contentType?: string): Promise<T> {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (contentType) headers["Content-Type"] = contentType;
    const res = await fetchImpl(`${root}${path}`, { method, headers, body });
    if (res.status === 401) onUnauthorized();
    if (!res.ok) throw new ApiError(res.status, await errorDetails(res));
    return (res.status === 204 ? undefined : await res.json()) as T;
  }

  const json = (v: unknown) => (v === undefined ? undefined : JSON.stringify(v));
  return {
    base: root,
    get: (p) => request("GET", p),
    post: (p, b) => request("POST", p, json(b), b === undefined ? undefined : "application/json"),
    put: (p, b) => request("PUT", p, json(b), "application/json"),
    patch: (p, b) => request("PATCH", p, json(b), "application/json"),
    del: (p) => request("DELETE", p),
    upload: (p, file) => {
      const form = new FormData();
      form.append("file", file);
      return request("POST", p, form);
    },
  };
}

/** API base: ?api=http://localhost:NNNN (remembered for the tab), else VITE_API_BASE, else :8000. */
export function resolveApiBase(): string {
  const fromQuery = new URLSearchParams(window.location.search).get("api");
  const ok = (v: string | null): v is string => !!v && /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(v);
  try {
    if (ok(fromQuery)) sessionStorage.setItem("chb-admin-api", fromQuery);
    const saved = sessionStorage.getItem("chb-admin-api");
    if (ok(saved)) return saved;
  } catch {
    if (ok(fromQuery)) return fromQuery;
  }
  return (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";
}
