// Render the real routes against a fake API. Handlers are keyed "METHOD /path"
// (query string ignored); each returns [status, body] or a body for 200.

import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import type { AdminRole } from "./api/types";
import { AppRoutes } from "./App";
import { AuthProvider } from "./auth";

export type Handler = (body: unknown, url: URL) => unknown;
export type Routes = Record<string, Handler | unknown>;

const NOW = "2026-11-12T10:00:00Z";

export const release = (id: string, status: string, extra: object = {}) => ({
  id,
  status,
  documents: { "deals-forecasting": 1, "contacts-import": 3 },
  created_by: "seed@ops",
  created_at: NOW,
  published_by: status === "draft" ? null : "publisher@ops",
  published_at: status === "draft" ? null : NOW,
  confirmed_by: null,
  live_since: status === "live" ? NOW : null,
  gate_report: null,
  job_id: null,
  ...extra,
});

export const overview = {
  live_release: release("r3", "live"),
  draft_release: release("r4", "draft"),
  last_published: release("r3", "live"),
  documents: 13,
  stale_documents: 2,
  proposed_questions: 5,
  accepted_questions: 20,
  last_eval_run: null,
  month_to_date_usd: 3.76,
  conversations_7d: 51,
};

export class FakeApi {
  calls: { method: string; path: string; body: unknown }[] = [];
  constructor(public routes: Routes) {}

  fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : init?.body;
    this.calls.push({ method, path: url.pathname, body });
    const key = `${method} ${url.pathname}`;
    const route = key in this.routes ? this.routes[key] : key === "GET /admin/overview" ? overview : undefined;
    if (route === undefined) return new Response(JSON.stringify({ detail: `no fake for ${key}` }), { status: 404 });
    const out = typeof route === "function" ? (route as Handler)(body, url) : route;
    const [status, payload] = Array.isArray(out) && typeof out[0] === "number" && out.length === 2 ? (out as [number, unknown]) : [200, out];
    return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
  });

  called(method: string, path: string) {
    return this.calls.filter((c) => c.method === method && c.path === path);
  }
}

export function renderAdmin(path: string, routes: Routes, role: AdminRole | null = "publisher") {
  sessionStorage.clear();
  if (role) {
    sessionStorage.setItem("chb-admin-session", JSON.stringify({ token: `token-${role}`, me: { sub: `admin-${role}`, admin_role: role } }));
  }
  const api = new FakeApi(routes);
  const view = render(
    <AuthProvider apiBase="http://api.test" fetchImpl={api.fetch as unknown as typeof fetch} pollMs={5}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>,
  );
  return { api, ...view };
}
