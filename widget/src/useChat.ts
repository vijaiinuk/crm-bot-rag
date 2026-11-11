import { useCallback, useEffect, useReducer, useRef } from "react";

import { chatReducer, initialChatState } from "./chatReducer";
import { HttpError, streamChat } from "./sse";
import type { TokenProvider } from "./types";

export class NoTokenProviderError extends Error {}

export function useChat(apiBase: string, getToken: TokenProvider) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const controller = useRef<AbortController | null>(null);
  // Read at send time, so a send never uses a stale conversation id.
  const conversationId = useRef(state.conversationId);
  conversationId.current = state.conversationId;

  useEffect(() => () => controller.current?.abort(), []);

  const send = useCallback(
    async (text: string) => {
      controller.current?.abort();
      const ctrl = new AbortController();
      controller.current = ctrl;
      const id = crypto.randomUUID();
      dispatch({ type: "send", userId: `${id}-q`, assistantId: id, text });

      const attempt = async (forceRefresh: boolean) =>
        streamChat({
          apiBase,
          token: await getToken(forceRefresh ? { forceRefresh } : undefined),
          message: text,
          conversationId: conversationId.current,
          signal: ctrl.signal,
          onEvent: (event) => dispatch({ type: "event", id, event }),
        });

      try {
        try {
          await attempt(false);
        } catch (err) {
          // One retry with a fresh token: the host's cached token may have expired.
          if (!(err instanceof HttpError && err.status === 401)) throw err;
          await attempt(true);
        }
        if (!ctrl.signal.aborted) dispatch({ type: "ended", id });
      } catch (err) {
        if (!ctrl.signal.aborted) dispatch({ type: "failed", id, message: describe(err) });
      }
    },
    [apiBase, getToken],
  );

  const stop = useCallback(() => {
    const id = state.activeId;
    controller.current?.abort();
    if (id) dispatch({ type: "stopped", id });
  }, [state.activeId]);

  return { state, send, stop, busy: state.activeId !== null };
}

function describe(err: unknown): string {
  if (err instanceof NoTokenProviderError) return "The help assistant isn't set up on this page.";
  if (err instanceof HttpError) {
    switch (err.status) {
      case 401:
        return "Your session has expired. Please sign in again.";
      case 403:
        return "You don't have access to the help assistant.";
      case 422:
        return "That message couldn't be sent. Try a shorter question.";
      case 429:
        return "Too many questions at once. Please wait a moment.";
    }
  }
  return "The help assistant is unavailable right now. Please try again.";
}
