import { describe, expect, it } from "vitest";

import { type AssistantMessage, type ChatAction, chatReducer, initialChatState } from "./chatReducer";
import { CITATIONS, DONE, META, RESTRICTED } from "./testing";
import type { ChatEvent } from "./types";

const send: ChatAction = { type: "send", userId: "u1", assistantId: "a1", text: "how do deals work" };
const ev = (event: ChatEvent): ChatAction => ({ type: "event", id: "a1", event });
const tok = (text: string) => ev({ type: "token", text });

function reduce(...actions: ChatAction[]) {
  return actions.reduce(chatReducer, initialChatState);
}

function assistant(state: ReturnType<typeof reduce>): AssistantMessage {
  const m = state.messages.find((x) => x.id === "a1");
  if (!m || m.role !== "assistant") throw new Error("no assistant message");
  return m;
}

describe("chatReducer", () => {
  it("send adds a user message and a streaming assistant message", () => {
    const s = reduce(send);
    expect(s.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(assistant(s).status).toBe("streaming");
    expect(s.activeId).toBe("a1");
  });

  it("accumulates an answer with citations", () => {
    const s = reduce(send, ev(META), tok("Open "), tok("Deals."), ev(CITATIONS), ev(DONE));
    const a = assistant(s);
    expect(a.status).toBe("done");
    expect(a.text).toBe("Open Deals.");
    expect(a.citations).toHaveLength(1);
    expect(a.traceId).toBe("t-1");
    expect(s.activeId).toBeNull();
  });

  it("keeps the conversation id from meta for the next send", () => {
    expect(reduce(send, ev(META), ev(DONE)).conversationId).toBe("c-1");
  });

  it("a refusal ends as refused, with no answer text", () => {
    const a = assistant(reduce(send, ev(META), ev(RESTRICTED), ev(DONE)));
    expect(a.status).toBe("refused");
    expect(a.refusal?.missing_modules).toEqual(["campaigns"]);
    expect(a.text).toBe("");
  });

  it("an error event keeps partial text", () => {
    const s = reduce(send, ev(META), tok("Let me check "), ev({ type: "error", code: "internal", message: "Something went wrong." }));
    const a = assistant(s);
    expect(a.status).toBe("error");
    expect(a.text).toBe("Let me check ");
    expect(a.error).toBe("Something went wrong.");
    expect(s.activeId).toBeNull();
  });

  it("a stream that ends without a terminal event is an error", () => {
    const a = assistant(reduce(send, ev(META), tok("Half"), { type: "ended", id: "a1" }));
    expect(a.status).toBe("error");
    expect(a.text).toBe("Half");
  });

  it("ignores events after the user stops", () => {
    const s = reduce(send, ev(META), tok("A"), { type: "stopped", id: "a1" }, tok("B"), ev(DONE));
    const a = assistant(s);
    expect(a.status).toBe("stopped");
    expect(a.text).toBe("A");
    expect(s.activeId).toBeNull();
  });

  it("ignores events for a different message id", () => {
    const s = reduce(send, { type: "event", id: "other", event: { type: "token", text: "x" } });
    expect(assistant(s).text).toBe("");
  });

  it("failed marks the message as an error with the given text", () => {
    const a = assistant(reduce(send, { type: "failed", id: "a1", message: "Session expired." }));
    expect(a.status).toBe("error");
    expect(a.error).toBe("Session expired.");
  });

  it("ended after done changes nothing", () => {
    const before = reduce(send, ev(META), tok("x"), ev(DONE));
    expect(chatReducer(before, { type: "ended", id: "a1" })).toBe(before);
  });
});
