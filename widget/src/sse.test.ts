import { describe, expect, it, vi } from "vitest";

import { HttpError, streamChat } from "./sse";
import { DONE, META, openResponse, sse, streamResponse } from "./testing";
import type { ChatEvent } from "./types";

const TOKEN: ChatEvent = { type: "token", text: "Open Deals." };

async function run(response: Response, signal?: AbortSignal) {
  const events: ChatEvent[] = [];
  const fetchImpl = vi.fn(async () => response);
  await streamChat({
    apiBase: "http://api.test",
    token: "tok",
    message: "hi",
    conversationId: "c-9",
    signal,
    onEvent: (e) => events.push(e),
    fetchImpl,
  });
  return { events, fetchImpl };
}

describe("streamChat", () => {
  it("posts the message with a bearer token and no entitlement fields", async () => {
    const { fetchImpl } = await run(streamResponse([sse(META), sse(DONE)]));
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test/chat");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    expect(JSON.parse(init.body as string)).toEqual({ message: "hi", conversation_id: "c-9" });
  });

  it("parses an event split across chunks", async () => {
    const whole = sse(TOKEN);
    const chunks = [whole.slice(0, 5), whole.slice(5, 17), whole.slice(17)];
    const { events } = await run(streamResponse(chunks));
    expect(events).toEqual([TOKEN]);
  });

  it("parses several events in one chunk", async () => {
    const { events } = await run(streamResponse([sse(META) + sse(TOKEN) + sse(DONE)]));
    expect(events.map((e) => e.type)).toEqual(["meta", "token", "done"]);
  });

  it("handles a multi-byte character split across chunks", async () => {
    const bytes = new TextEncoder().encode(sse({ type: "token", text: "Deals → Pipeline" }));
    const cut = bytes.indexOf(0xe2) + 1; // inside the 3-byte arrow
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(bytes.slice(0, cut));
        c.enqueue(bytes.slice(cut));
        c.close();
      },
    });
    const { events } = await run(new Response(body, { status: 200 }));
    expect(events).toEqual([{ type: "token", text: "Deals → Pipeline" }]);
  });

  it("ignores unknown event names and malformed JSON", async () => {
    const chunks = ["event: surprise\ndata: {}\n\n", "event: token\ndata: {not json\n\n", sse(TOKEN)];
    const { events } = await run(streamResponse(chunks));
    expect(events).toEqual([TOKEN]);
  });

  it("raises HttpError on a non-2xx status without emitting events", async () => {
    const onEvent = vi.fn();
    await expect(
      streamChat({
        apiBase: "http://api.test",
        token: "tok",
        message: "hi",
        onEvent,
        fetchImpl: async () => new Response("{}", { status: 401 }),
      }),
    ).rejects.toEqual(new HttpError(401));
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("stops reading when aborted", async () => {
    const open = openResponse();
    const ctrl = new AbortController();
    const events: ChatEvent[] = [];
    const done = streamChat({
      apiBase: "http://api.test",
      token: "tok",
      message: "hi",
      signal: ctrl.signal,
      onEvent: (e) => events.push(e),
      fetchImpl: async () => open.response,
    });
    open.push(sse(META));
    await vi.waitFor(() => expect(events).toHaveLength(1));
    ctrl.abort();
    await done;
    expect(events.map((e) => e.type)).toEqual(["meta"]);
  });
});
