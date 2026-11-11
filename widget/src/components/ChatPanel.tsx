import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";

import type { TokenProvider } from "../types";
import { useChat } from "../useChat";
import { Message } from "./Message";

const MAX_CHARS = 2000; // mirrors ChatRequest.message on the server

interface Props {
  apiBase: string;
  getToken: TokenProvider;
  heading: string;
  defaultOpen?: boolean;
}

export function ChatPanel({ apiBase, getToken, heading, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const [draft, setDraft] = useState("");
  const { state, send, stop, busy } = useChat(apiBase, getToken);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [state.messages]);

  useEffect(() => {
    if (open && !busy) inputRef.current?.focus();
  }, [open, busy]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    void send(text);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
  };

  if (!open) {
    return (
      <button type="button" className="launcher" onClick={() => setOpen(true)} aria-label={`Open ${heading}`}>
        {heading}
      </button>
    );
  }

  return (
    <section className="panel" aria-label={heading}>
      <header className="panel-header">
        <h2>{heading}</h2>
        <button type="button" className="icon-button" onClick={() => setOpen(false)} aria-label={`Close ${heading}`}>
          ×
        </button>
      </header>

      <div className="messages" ref={listRef} aria-live="polite">
        {state.messages.length === 0 && (
          <p className="empty">Ask how to do something in the CRM, for example “how do I import contacts?”</p>
        )}
        {state.messages.map((m) => (
          <Message key={m.id} message={m} />
        ))}
      </div>

      <form className="composer" onSubmit={submit}>
        <textarea
          ref={inputRef}
          aria-label="Your question"
          placeholder="Ask a question…"
          rows={2}
          maxLength={MAX_CHARS}
          value={draft}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {busy ? (
          <button type="button" className="secondary" onClick={stop}>
            Stop
          </button>
        ) : (
          <button type="submit" disabled={!draft.trim()}>
            Send
          </button>
        )}
      </form>
    </section>
  );
}
