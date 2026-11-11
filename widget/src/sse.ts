// POST /chat and parse the SSE response.
//
// Not EventSource: it only does GET and can't send an Authorization header.

import { type EventSourceMessage, createParser } from "eventsource-parser";

import { CHAT_EVENT_TYPES, type ChatEvent } from "./types";

export class HttpError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`HTTP ${status}`);
    this.name = "HttpError";
    this.status = status;
  }
}

export interface StreamChatOptions {
  apiBase: string;
  token: string;
  message: string;
  conversationId?: string | null;
  signal?: AbortSignal;
  onEvent: (event: ChatEvent) => void;
  fetchImpl?: typeof fetch;
}

/** Resolves when the stream closes or is aborted; rejects on HTTP or network failure. */
export async function streamChat(opts: StreamChatOptions): Promise<void> {
  const fetchImpl = opts.fetchImpl ?? fetch;
  const response = await fetchImpl(`${opts.apiBase.replace(/\/$/, "")}/chat`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${opts.token}`,
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ message: opts.message, conversation_id: opts.conversationId ?? null }),
    signal: opts.signal,
  });
  if (!response.ok) throw new HttpError(response.status);
  if (!response.body) throw new Error("response has no body");

  const parser = createParser({
    onEvent: (message) => {
      const event = toChatEvent(message);
      if (event && !opts.signal?.aborted) opts.onEvent(event);
    },
  });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const cancel = () => void reader.cancel().catch(() => {});
  opts.signal?.addEventListener("abort", cancel, { once: true });
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done || opts.signal?.aborted) break;
      parser.feed(decoder.decode(value, { stream: true }));
    }
    parser.feed(decoder.decode());
  } catch (err) {
    if (!opts.signal?.aborted) throw err;
  } finally {
    opts.signal?.removeEventListener("abort", cancel);
  }
}

function toChatEvent(message: EventSourceMessage): ChatEvent | null {
  if (!message.event || !CHAT_EVENT_TYPES.has(message.event)) return null;
  try {
    const data: unknown = JSON.parse(message.data);
    if (typeof data !== "object" || data === null) return null;
    return { ...data, type: message.event } as ChatEvent;
  } catch {
    return null;
  }
}
