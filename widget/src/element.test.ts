import { fireEvent, waitFor, within } from "@testing-library/dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type CrmHelpBot } from "./element";
import "./element";
import { DONE, META, sse, streamResponse } from "./testing";

afterEach(() => {
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

function mount(attrs: Record<string, string> = {}): CrmHelpBot {
  const el = document.createElement("crm-help-bot") as CrmHelpBot;
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  document.body.append(el);
  return el;
}

// user-event dispatches input to document.activeElement, which is the host element
// when focus is inside a shadow root, so React never sees the typing. Dispatch on
// the textarea directly; real typing and Enter-to-send are covered in ChatPanel.test.tsx.
async function ask(el: CrmHelpBot, text: string) {
  const ui = shadow(el);
  fireEvent.change(await ui.findByRole("textbox", { name: /question/i }), { target: { value: text } });
  fireEvent.click(ui.getByRole("button", { name: /send/i }));
}

function shadow(el: CrmHelpBot) {
  if (!el.shadowRoot) throw new Error("no shadow root");
  return within(el.shadowRoot as unknown as HTMLElement);
}

describe("<crm-help-bot>", () => {
  it("registers and renders inside a shadow root with scoped styles", async () => {
    const el = mount({ "api-base": "http://api.test" });
    expect(customElements.get("crm-help-bot")).toBeDefined();
    await waitFor(() => shadow(el).getByRole("button", { name: /help/i }));
    expect(el.shadowRoot?.querySelector("style")?.textContent).toContain(":host");
    expect(document.querySelector("style")).toBeNull();
  });

  it("uses the token provider and never puts the token in the DOM", async () => {
    const fetchMock = vi.fn(async () => streamResponse([sse(META), sse({ type: "token", text: "hello" }), sse(DONE)]));
    vi.stubGlobal("fetch", fetchMock);
    const el = mount({ "api-base": "http://api.test", open: "" });
    el.tokenProvider = async () => "secret-token-123";

    const ui = shadow(el);
    await ask(el, "hi");
    await ui.findByText("hello");

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(document.documentElement.outerHTML).not.toContain("secret-token-123");
    expect(el.shadowRoot?.innerHTML).not.toContain("secret-token-123");
  });

  it("without a token provider, shows a configuration error instead of calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const el = mount({ "api-base": "http://api.test", open: "" });
    const ui = shadow(el);
    await ask(el, "hi");
    await ui.findByText(/isn't set up/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("resetConversation clears the messages", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => streamResponse([sse(META), sse({ type: "token", text: "hello" }), sse(DONE)])));
    const el = mount({ "api-base": "http://api.test", open: "" });
    el.tokenProvider = async () => "t";
    const ui = shadow(el);
    await ask(el, "hi");
    await ui.findByText("hello");
    el.resetConversation();
    await waitFor(() => expect(ui.queryByText("hello")).toBeNull());
  });
});
