// Dev harness: plays the CRM host. Picks a persona, gets it a token from the
// local-only /dev/token endpoint, and hands the widget a tokenProvider, the
// same contract the real CRM will implement with its own session token.

import "../src/element";
import type { TokenProvider } from "../src/types";

const widget = document.querySelector("crm-help-bot");
const select = document.querySelector<HTMLSelectElement>("#persona");
const modules = document.querySelector<HTMLElement>("#modules");
if (!widget || !select || !modules) throw new Error("harness markup missing");

// ?api=http://localhost:8001 points the harness at another API instance.
const apiOverride = new URLSearchParams(location.search).get("api");
if (apiOverride && /^http:\/\/localhost:\d+$/.test(apiOverride)) {
  widget.setAttribute("api-base", apiOverride);
}
const apiBase = widget.getAttribute("api-base") ?? "http://localhost:8000";
const STORAGE_KEY = "chb-harness-persona";
const REFRESH_MARGIN_MS = 60_000;

function tokenProviderFor(persona: string): TokenProvider {
  let cached: { token: string; expiresAt: number } | null = null;
  return async ({ forceRefresh = false } = {}) => {
    if (!forceRefresh && cached && Date.now() < cached.expiresAt - REFRESH_MARGIN_MS) {
      return cached.token;
    }
    const r = await fetch(`${apiBase}/dev/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona }),
    });
    if (!r.ok) throw new Error(`dev token request failed: ${r.status}`);
    const body = (await r.json()) as { token: string; expires_in: number };
    cached = { token: body.token, expiresAt: Date.now() + body.expires_in * 1000 };
    return body.token;
  };
}

async function showModules(provider: TokenProvider) {
  modules!.textContent = "…";
  try {
    const r = await fetch(`${apiBase}/me`, { headers: { Authorization: `Bearer ${await provider()}` } });
    const me = (await r.json()) as { allowed_modules: string[] };
    modules!.textContent = `Modules: ${me.allowed_modules.join(", ")}`;
  } catch {
    modules!.textContent = "Modules: (API unreachable)";
  }
}

function usePersona(persona: string) {
  const provider = tokenProviderFor(persona);
  widget!.tokenProvider = provider;
  widget!.resetConversation(); // a different user: start a clean conversation
  try {
    localStorage.setItem(STORAGE_KEY, persona);
  } catch {
    /* storage may be unavailable; the harness works without it */
  }
  void showModules(provider);
}

async function init() {
  let personas: string[];
  try {
    const r = await fetch(`${apiBase}/dev/personas`);
    personas = (await r.json()) as string[];
  } catch {
    modules!.textContent = `API not reachable at ${apiBase}. Is \`make run\` going?`;
    return;
  }
  for (const p of personas) select!.add(new Option(p, p));

  let saved: string | null = null;
  try {
    saved = localStorage.getItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  select!.value = saved && personas.includes(saved) ? saved : (personas[0] ?? "");
  select!.addEventListener("change", () => usePersona(select!.value));
  if (select!.value) usePersona(select!.value);
}

void init();
