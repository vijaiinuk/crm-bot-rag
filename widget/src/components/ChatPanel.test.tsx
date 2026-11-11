import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CITATIONS, DONE, META, RESTRICTED, openResponse, sse, streamResponse } from "../testing";
import { ChatPanel } from "./ChatPanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function setup(responses: Array<() => Response>, getToken = vi.fn(async () => "tok")) {
  const fetchMock = vi.fn(async () => {
    const next = responses.shift();
    if (!next) throw new Error("unexpected fetch");
    return next();
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<ChatPanel apiBase="http://api.test" getToken={getToken} heading="Help" defaultOpen />);
  return { fetchMock, getToken, user: userEvent.setup() };
}

async function ask(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByRole("textbox", { name: /question/i }), text);
  await user.keyboard("{Enter}");
}

describe("ChatPanel", () => {
  it("streams an answer and then shows sources", async () => {
    const { user } = setup([
      () =>
        streamResponse([
          sse(META),
          sse({ type: "token", text: "Open **Deals** " }),
          sse({ type: "token", text: "settings." }),
          sse(CITATIONS),
          sse(DONE),
        ]),
    ]);
    await ask(user, "how do deal stages work");
    expect(await screen.findByText("how do deal stages work")).toBeTruthy();
    await screen.findByText("Automating deal stage changes");
    expect(screen.getByText("Deals").tagName).toBe("STRONG");
    expect(screen.getByRole("textbox", { name: /question/i })).toHaveProperty("value", "");
  });

  it("shows the refusal card and no sources for a restricted answer", async () => {
    const { user } = setup([() => streamResponse([sse(META), sse(RESTRICTED), sse(DONE)])]);
    await ask(user, "campaign emails");
    const card = await screen.findByRole("note");
    expect(card.textContent).toContain("Campaigns");
    expect(screen.queryByText(/sources/i)).toBeNull();
  });

  it("sends the conversation id back on the next question", async () => {
    const { user, fetchMock } = setup([
      () => streamResponse([sse(META), sse({ type: "token", text: "a" }), sse(DONE)]),
      () => streamResponse([sse(META), sse({ type: "token", text: "b" }), sse(DONE)]),
    ]);
    await ask(user, "first");
    await screen.findByText("a");
    await ask(user, "second");
    await screen.findByText("b");
    const bodies = fetchMock.mock.calls.map((c) => JSON.parse((c as unknown as [string, RequestInit])[1].body as string));
    expect(bodies[0].conversation_id).toBeNull();
    expect(bodies[1].conversation_id).toBe("c-1");
  });

  it("on 401 asks the host for a fresh token and retries once", async () => {
    const getToken = vi.fn(async (opts?: { forceRefresh?: boolean }) => (opts?.forceRefresh ? "fresh" : "stale"));
    const { user, fetchMock } = setup(
      [
        () => new Response("{}", { status: 401 }),
        () => streamResponse([sse(META), sse({ type: "token", text: "ok" }), sse(DONE)]),
      ],
      getToken,
    );
    await ask(user, "hi");
    await screen.findByText("ok");
    expect(getToken).toHaveBeenLastCalledWith({ forceRefresh: true });
    const auth = fetchMock.mock.calls.map((c) => ((c as unknown as [string, RequestInit])[1].headers as Record<string, string>).Authorization);
    expect(auth).toEqual(["Bearer stale", "Bearer fresh"]);
  });

  it("a second 401 shows a session error instead of looping", async () => {
    const { user, fetchMock } = setup([
      () => new Response("{}", { status: 401 }),
      () => new Response("{}", { status: 401 }),
    ]);
    await ask(user, "hi");
    expect(await screen.findByText(/session has expired/i)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("stop ends the stream and keeps partial text", async () => {
    const open = openResponse();
    const { user } = setup([() => open.response]);
    await ask(user, "hi");
    open.push(sse(META) + sse({ type: "token", text: "Partial answer" }));
    await screen.findByText("Partial answer");
    await user.click(screen.getByRole("button", { name: /stop/i }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: /question/i })).toHaveProperty("disabled", false));
    expect(screen.getByText(/stopped/i)).toBeTruthy();
  });

  it("disables input while an answer is streaming", async () => {
    const open = openResponse();
    const { user } = setup([() => open.response]);
    await ask(user, "hi");
    await waitFor(() => expect(screen.getByRole("textbox", { name: /question/i })).toHaveProperty("disabled", true));
    open.push(sse(META) + sse({ type: "token", text: "x" }) + sse(DONE));
    open.close();
    await waitFor(() => expect(screen.getByRole("textbox", { name: /question/i })).toHaveProperty("disabled", false));
  });
});
