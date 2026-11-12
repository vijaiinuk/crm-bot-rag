import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, createApi } from "./api/client";
import { release, renderAdmin } from "./test-utils";

afterEach(() => {
  cleanup();
  sessionStorage.clear();
});

const DIFF = {
  module_changes: [
    { doc_id: "deals-forecasting", change: "widened", before: ["deals", "reports"], after: ["reports"], dropped: ["deals"], added: [] },
    { doc_id: "core-search-tips", change: "new", before: null, after: ["core"], dropped: [], added: [] },
  ],
  orphaned_labels: [{ question_id: "q-0001", label: "deals-stage-automation#triggers" }],
};

const RELEASES = [release("r4", "draft"), release("r3", "live"), release("r2", "superseded")];

describe("API client", () => {
  it("attaches the bearer token and reports FastAPI error details", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ detail: ["unknown module(s): dealz", "title is missing"] }), { status: 422 }));
    const onUnauthorized = vi.fn();
    const api = createApi("http://api.test/", () => "tok", onUnauthorized, fetchImpl as unknown as typeof fetch);
    const err = await api.get("/admin/documents").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).details).toEqual(["unknown module(s): dealz", "title is missing"]);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test/admin/documents");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("a 401 signs the admin out", async () => {
    const onUnauthorized = vi.fn();
    const api = createApi("http://api.test", () => "expired", onUnauthorized, (async () => new Response("{}", { status: 401 })) as unknown as typeof fetch);
    await api.get("/admin/me").catch(() => {});
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});

describe("role gating", () => {
  const routes = { "GET /admin/releases": RELEASES, "GET /admin/releases/draft/diff": DIFF };

  it("an editor sees the draft but no publish button", async () => {
    renderAdmin("/releases", routes, "editor");
    await screen.findByRole("heading", { name: /draft r4/i });
    expect(screen.queryByRole("button", { name: /publish/i })).toBeNull();
  });

  it("a publisher can publish, and the page warns about widening and orphaned labels", async () => {
    renderAdmin("/releases", routes, "publisher");
    expect(await screen.findByRole("button", { name: "Publish r4" })).toBeTruthy();
    expect(screen.getByText(/would become visible to more users/i)).toBeTruthy();
    expect(screen.getByText(/point at sections that won't exist/i)).toBeTruthy();
    const widenedRow = screen.getByRole("link", { name: "deals-forecasting" }).closest("tr");
    expect(widenedRow?.className).toContain("flag");
  });

  it("a viewer sees no upload button", async () => {
    renderAdmin("/documents", { "GET /admin/documents": [] }, "viewer");
    await screen.findByRole("heading", { name: "Documents" });
    expect(screen.queryByRole("button", { name: /upload/i })).toBeNull();
  });

  it("signed out shows the dev sign-in", async () => {
    renderAdmin("/", { "GET /dev/admins": { "editor@ops": "editor" } }, null);
    expect(await screen.findByRole("button", { name: /sign in as editor/i })).toBeTruthy();
  });
});

describe("document upload", () => {
  it("shows why a version was rejected", async () => {
    const { api } = renderAdmin(
      "/documents",
      {
        "GET /admin/documents": [],
        "POST /admin/documents": [
          201,
          {
            doc_id: "deals-x",
            version: 2,
            status: "rejected",
            validation_errors: ["unknown module(s): dealz"],
            title: "X",
            modules: [],
            anchors: [],
            uploaded_by: "admin-editor",
            uploaded_at: "2026-11-12T10:00:00Z",
            content_sha256: "x",
            size_bytes: 10,
          },
        ],
      },
      "editor",
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /upload markdown/i }));
    const dialog = screen.getByRole("dialog", { name: /upload a markdown document/i });
    const file = new File(["---\ndoc_id: deals-x\n---\n"], "deals-x.md", { type: "text/markdown" });
    await user.upload(within(dialog).getByLabelText(/markdown file/i), file);
    await user.click(within(dialog).getByRole("button", { name: "Upload" }));
    expect(await within(dialog).findByText(/unknown module\(s\): dealz/)).toBeTruthy();
    expect(within(dialog).getByText(/rejected/)).toBeTruthy();
    expect(api.called("POST", "/admin/documents")).toHaveLength(1);
  });

  it("shows the API's reasons when a file can't be identified", async () => {
    renderAdmin(
      "/documents",
      { "GET /admin/documents": [], "POST /admin/documents": [422, { detail: ["missing frontmatter: the file must start with a --- block"] }] },
      "editor",
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /upload markdown/i }));
    const dialog = screen.getByRole("dialog");
    await user.upload(within(dialog).getByLabelText(/markdown file/i), new File(["# hi"], "x.md"));
    await user.click(within(dialog).getByRole("button", { name: "Upload" }));
    expect(await within(dialog).findByRole("alert")).toHaveProperty("textContent", "missing frontmatter: the file must start with a --- block");
  });
});

describe("widening confirmation", () => {
  it("a publisher reviews the widened docs and confirms; the release goes live", async () => {
    let status = "awaiting_confirmation";
    const gate = {
      checks: [
        { name: "permission_suite", status: "pass", detail: "ok" },
        { name: "access_widening", status: "needs_confirmation", detail: "More users would see: deals-forecasting." },
      ],
      module_changes: DIFF.module_changes,
      orphaned_labels: [],
    };
    const { api } = renderAdmin("/releases/r5", {
      "GET /admin/releases/r5": () => release("r5", status, { gate_report: gate, confirmed_by: status === "live" ? "admin-publisher" : null }),
      "POST /admin/releases/r5/confirm": () => {
        status = "live";
        return release("r5", "live");
      },
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /review and confirm/i }));
    const dialog = screen.getByRole("dialog", { name: /confirm wider access/i });
    expect(within(dialog).getByRole("link", { name: "deals-forecasting" })).toBeTruthy();
    expect(within(dialog).queryByText("core-search-tips")).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: /confirm and make live/i }));
    await waitFor(() => expect(api.called("POST", "/admin/releases/r5/confirm")).toHaveLength(1));
    expect(await screen.findByText(/widening confirmed by admin-publisher/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /review and confirm/i })).toBeNull();
  });

  it("an editor can't confirm", async () => {
    renderAdmin("/releases/r5", { "GET /admin/releases/r5": release("r5", "awaiting_confirmation") }, "editor");
    await screen.findByRole("heading", { name: "Release r5" });
    expect(screen.queryByRole("button", { name: /review and confirm/i })).toBeNull();
  });
});

describe("costs", () => {
  it("renders totals, per-client months and sessions from the summary", async () => {
    const daily = Array.from({ length: 30 }, (_, i) => ({ date: `2026-10-${String(i + 1).padStart(2, "0")}`, chat: 0.1, eval: 0, ingest: 0 }));
    renderAdmin("/costs", {
      "GET /admin/prices": [],
      "GET /admin/costs": {
        start: "2026-10-14",
        end: "2026-11-12",
        estimated: true,
        total_usd: 8.52,
        by_bucket: { chat: 3.86, eval: 4.52, ingest: 0.13 },
        by_tenant_month: [
          { tenant: "acme", month: "2026-11", cost_usd: 0.87, calls: 120 },
          { tenant: "globex", month: "2026-11", cost_usd: 0.57, calls: 80 },
        ],
        by_model: [{ model_id: "answer-medium", calls: 200, input_tokens: 700000, output_tokens: 60000, cost_usd: 3.0 }],
        daily,
        top_conversations: [{ conversation_id: "33627894-928d-4bae-8e88-b5957b9d2927", tenant: "globex", cost_usd: 0.05 }],
      },
    });
    expect(await screen.findByText("$8.52")).toBeTruthy();
    expect(screen.getByText("$4.52")).toBeTruthy();
    expect(screen.getByRole("link", { name: "acme" }).getAttribute("href")).toBe("/conversations?tenant=acme");
    expect(screen.getByRole("link", { name: "33627894" }).getAttribute("href")).toBe("/conversations/33627894-928d-4bae-8e88-b5957b9d2927");
    expect(screen.getByRole("img", { name: /daily estimated llm cost/i })).toBeTruthy();
  });
});
