// Mirror of src/chatbot/events.py: the SSE wire contract.
// Keep in step with the Python models; the server is the source of truth.

export interface Citation {
  chunk_id: string;
  doc_id: string;
  anchor: string;
  title: string;
  breadcrumb: string;
}

export type RefusalKind = "not_found" | "restricted" | "out_of_scope";

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
}

export type ChatEvent =
  | {
      type: "meta";
      trace_id: string;
      conversation_id: string;
      index_version: string;
      prompt_version: string;
      model_id: string;
    }
  | { type: "token"; text: string }
  | { type: "citations"; items: Citation[] }
  | { type: "refusal"; kind: RefusalKind; message: string; missing_modules: string[] }
  | { type: "error"; code: string; message: string }
  | { type: "done"; usage: TokenUsage };

export type ChatEventType = ChatEvent["type"];

export const CHAT_EVENT_TYPES: ReadonlySet<string> = new Set<ChatEventType>([
  "meta",
  "token",
  "citations",
  "refusal",
  "error",
  "done",
]);

/** Supplied by the host page. Called before every request; the host owns caching and refresh. */
export type TokenProvider = (options?: { forceRefresh?: boolean }) => Promise<string>;
