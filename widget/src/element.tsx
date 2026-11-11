// <crm-help-bot api-base="https://..." heading="Help" open></crm-help-bot>
// element.tokenProvider = async ({ forceRefresh } = {}) => jwt;
//
// The token is only ever passed through the `tokenProvider` property, never an
// attribute: attributes end up in outerHTML, devtools and error reports.

import { type Root, createRoot } from "react-dom/client";

import { ChatPanel } from "./components/ChatPanel";
import css from "./styles.css?inline";
import type { TokenProvider } from "./types";
import { NoTokenProviderError } from "./useChat";

export class CrmHelpBot extends HTMLElement {
  static observedAttributes = ["api-base", "heading", "open"];

  #root: Root | null = null;
  #mount: HTMLDivElement;
  #tokenProvider: TokenProvider | null = null;
  #session = 0;

  constructor() {
    super();
    const shadow = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = css;
    this.#mount = document.createElement("div");
    shadow.append(style, this.#mount);
  }

  get tokenProvider(): TokenProvider | null {
    return this.#tokenProvider;
  }

  set tokenProvider(provider: TokenProvider | null) {
    this.#tokenProvider = provider;
  }

  /** Start a fresh conversation, e.g. when the signed-in user changes. */
  resetConversation(): void {
    this.#session += 1;
    this.#render();
  }

  connectedCallback(): void {
    this.#root ??= createRoot(this.#mount);
    this.#render();
  }

  disconnectedCallback(): void {
    this.#root?.unmount();
    this.#root = null;
  }

  attributeChangedCallback(): void {
    this.#render();
  }

  #getToken: TokenProvider = (options) => {
    const provider = this.#tokenProvider;
    return provider ? provider(options) : Promise.reject(new NoTokenProviderError());
  };

  #render(): void {
    this.#root?.render(
      <ChatPanel
        key={this.#session}
        apiBase={this.getAttribute("api-base") ?? ""}
        heading={this.getAttribute("heading") ?? "Help"}
        defaultOpen={this.hasAttribute("open")}
        getToken={this.#getToken}
      />,
    );
  }
}

if (!customElements.get("crm-help-bot")) {
  customElements.define("crm-help-bot", CrmHelpBot);
}

declare global {
  interface HTMLElementTagNameMap {
    "crm-help-bot": CrmHelpBot;
  }
}
