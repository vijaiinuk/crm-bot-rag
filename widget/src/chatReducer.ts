// Pure chat state: one user message + one assistant message per turn.
//
// An assistant message is `streaming` until a terminal action; after that,
// late events for it are ignored (e.g. after the user presses Stop).

import type { ChatEvent, Citation, RefusalKind } from "./types";

export type AssistantStatus = "streaming" | "done" | "refused" | "error" | "stopped";

export interface UserMessage {
  id: string;
  role: "user";
  text: string;
}

export interface AssistantMessage {
  id: string;
  role: "assistant";
  status: AssistantStatus;
  text: string;
  citations: Citation[];
  refusal?: { kind: RefusalKind; message: string; missing_modules: string[] };
  error?: string;
  traceId?: string;
}

export type ChatMessage = UserMessage | AssistantMessage;

export interface ChatState {
  conversationId: string | null;
  messages: ChatMessage[];
  /** The assistant message currently streaming, if any. */
  activeId: string | null;
}

export type ChatAction =
  | { type: "send"; userId: string; assistantId: string; text: string }
  | { type: "event"; id: string; event: ChatEvent }
  | { type: "failed"; id: string; message: string }
  | { type: "ended"; id: string }
  | { type: "stopped"; id: string }
  /** The server no longer knows this conversation (404): the next question starts a new one. */
  | { type: "conversationReset" };

export const initialChatState: ChatState = { conversationId: null, messages: [], activeId: null };

const INTERRUPTED = "The connection was interrupted. Please try again.";

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  if (action.type === "conversationReset") {
    return { ...state, conversationId: null };
  }

  if (action.type === "send") {
    return {
      ...state,
      activeId: action.assistantId,
      messages: [
        ...state.messages,
        { id: action.userId, role: "user", text: action.text },
        { id: action.assistantId, role: "assistant", status: "streaming", text: "", citations: [] },
      ],
    };
  }

  const current = state.messages.find((m) => m.id === action.id);
  if (!current || current.role !== "assistant" || current.status !== "streaming") return state;

  switch (action.type) {
    case "event":
      return applyEvent(state, current, action.event);
    case "failed":
      return finish(state, { ...current, status: "error", error: action.message });
    case "ended":
      return finish(state, { ...current, status: "error", error: INTERRUPTED });
    case "stopped":
      return finish(state, { ...current, status: "stopped" });
  }
}

function applyEvent(state: ChatState, msg: AssistantMessage, event: ChatEvent): ChatState {
  switch (event.type) {
    case "meta":
      return replace({ ...state, conversationId: event.conversation_id }, { ...msg, traceId: event.trace_id });
    case "token":
      return replace(state, { ...msg, text: msg.text + event.text });
    case "citations":
      return replace(state, { ...msg, citations: event.items });
    case "refusal": {
      const { kind, message, missing_modules } = event;
      return replace(state, { ...msg, refusal: { kind, message, missing_modules } });
    }
    case "error":
      return finish(state, { ...msg, status: "error", error: event.message });
    case "done":
      return finish(state, { ...msg, status: msg.refusal ? "refused" : "done" });
  }
}

function replace(state: ChatState, msg: AssistantMessage): ChatState {
  return { ...state, messages: state.messages.map((m) => (m.id === msg.id ? msg : m)) };
}

function finish(state: ChatState, msg: AssistantMessage): ChatState {
  return { ...replace(state, msg), activeId: null };
}
