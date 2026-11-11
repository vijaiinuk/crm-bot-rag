import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AssistantMessage } from "../chatReducer";
import { Message } from "./Message";

afterEach(cleanup);

function renderAnswer(text: string) {
  const message: AssistantMessage = { id: "a", role: "assistant", status: "done", text, citations: [] };
  return render(<Message message={message} />).container;
}

describe("Message markdown rendering is inert (model output is untrusted)", () => {
  it("renders basic markdown", () => {
    const c = renderAnswer("1. Open **Deals**\n2. Save");
    expect(c.querySelector("ol li strong")?.textContent).toBe("Deals");
  });

  it("drops raw HTML elements", () => {
    const c = renderAnswer('Hi <img src=x onerror="alert(1)"> <b>bold</b>');
    expect(c.querySelector("img")).toBeNull();
    expect(c.querySelector("b")).toBeNull();
    expect(c.innerHTML).not.toContain("onerror");
  });

  it("never renders or runs a script tag", () => {
    const spy = vi.fn();
    (globalThis as Record<string, unknown>).__pwned = spy;
    const c = renderAnswer("<script>__pwned()</script>");
    expect(c.querySelector("script")).toBeNull();
    expect(spy).not.toHaveBeenCalled();
  });

  it.each(["javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<b>x</b>", "vbscript:x"])(
    "neutralises dangerous link %s",
    (href) => {
      const c = renderAnswer(`[click](${href})`);
      const a = c.querySelector("a");
      expect(a?.getAttribute("href") ?? "").toBe("");
    },
  );

  it.each(["https://docs.example.com/x", "/help/deals", "#triggers", "mailto:help@example.com"])(
    "keeps safe link %s and opens external ones safely",
    (href) => {
      const a = renderAnswer(`[ok](${href})`).querySelector("a");
      expect(a?.getAttribute("href")).toBe(href);
      if (href.startsWith("http")) {
        expect(a?.getAttribute("target")).toBe("_blank");
        expect(a?.getAttribute("rel")).toContain("noopener");
      }
    },
  );

  it("renders user text literally, not as markdown", () => {
    const c = render(<Message message={{ id: "u", role: "user", text: "**not bold** <i>x</i>" }} />).container;
    expect(c.querySelector("strong, i")).toBeNull();
    expect(c.textContent).toContain("**not bold** <i>x</i>");
  });
});
