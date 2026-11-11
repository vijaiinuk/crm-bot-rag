// Test helpers: build fetch Responses that stream SSE in arbitrary chunks.

import type { ChatEvent } from "./types";

export function sse(event: ChatEvent): string {
  const { type, ...data } = event;
  return `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
}

export function streamResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}

/** A response whose body never closes until `close()` is called. */
export function openResponse(): { response: Response; push: (s: string) => void; close: () => void } {
  const encoder = new TextEncoder();
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => void (ctrl = c) });
  return {
    response: new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    push: (s) => ctrl.enqueue(encoder.encode(s)),
    close: () => ctrl.close(),
  };
}

export const META: ChatEvent = {
  type: "meta",
  trace_id: "t-1",
  conversation_id: "c-1",
  index_version: "mock",
  prompt_version: "mock",
  model_id: "mock",
};

export const DONE: ChatEvent = { type: "done", usage: { input_tokens: 3, output_tokens: 4 } };

export const CITATIONS: ChatEvent = {
  type: "citations",
  items: [
    {
      chunk_id: "mock:deals-stage-automation#triggers:0",
      doc_id: "deals-stage-automation",
      anchor: "triggers",
      title: "Automating deal stage changes",
      breadcrumb: "Deals > Stage automation > Triggers",
    },
  ],
};

export const RESTRICTED: ChatEvent = {
  type: "refusal",
  kind: "restricted",
  message: "This question involves Campaigns, which isn't included in your current access.",
  missing_modules: ["campaigns"],
};
