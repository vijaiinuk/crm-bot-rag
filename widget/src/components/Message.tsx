import Markdown, { type Components } from "react-markdown";

import type { ChatMessage } from "../chatReducer";
import { Citations } from "./Citations";
import { RefusalCard } from "./RefusalCard";

// Answer text is model output: treat it as untrusted. Raw HTML is dropped
// (skipHtml, no rehype-raw) and only these URL forms survive.
const SAFE_URL = /^(?:https?:\/\/|mailto:|\/(?!\/)|#|\.{0,2}\/)/i;

export function safeUrl(url: string): string {
  return SAFE_URL.test(url.trim()) ? url : "";
}

const components: Components = {
  a: ({ href, children }) =>
    href && /^https?:/i.test(href) ? (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ) : (
      <a href={href || undefined}>{children}</a>
    ),
};

export function Message({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="msg msg-user">
        <p>{message.text}</p>
      </div>
    );
  }

  const streaming = message.status === "streaming";
  return (
    <div className="msg msg-assistant" aria-busy={streaming}>
      {message.text && (
        <div className="answer">
          <Markdown skipHtml urlTransform={safeUrl} components={components}>
            {message.text}
          </Markdown>
        </div>
      )}
      {streaming && !message.text && <p className="typing">Looking that up…</p>}
      {message.refusal && <RefusalCard kind={message.refusal.kind} message={message.refusal.message} />}
      {message.status === "done" && message.citations.length > 0 && <Citations items={message.citations} />}
      {message.status === "stopped" && <p className="status">Stopped.</p>}
      {message.status === "error" && (
        <p className="status status-error" role="alert">
          {message.error}
        </p>
      )}
    </div>
  );
}
