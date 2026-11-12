// Admin session: a dev-minted token now, the CRM's SSO later. The role shown in
// the UI comes from /admin/me; the server enforces every action regardless.

import { type ReactNode, createContext, useCallback, useContext, useMemo, useState } from "react";

import { type Api, createApi } from "./api/client";
import type { AdminRole, Me } from "./api/types";

const STORAGE_KEY = "chb-admin-session";
const RANK: Record<AdminRole, number> = { viewer: 0, editor: 1, publisher: 2 };

interface Session {
  token: string;
  me: Me;
}

interface AuthState {
  api: Api;
  me: Me | null;
  pollMs: number;
  signIn: (token: string) => Promise<void>;
  signOut: () => void;
  can: (minimum: AdminRole) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

function load(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function save(session: Session | null) {
  try {
    if (session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable: the session lasts until reload */
  }
}

export function AuthProvider({
  apiBase,
  children,
  pollMs = 1000,
  fetchImpl,
}: {
  apiBase: string;
  children: ReactNode;
  pollMs?: number;
  fetchImpl?: typeof fetch;
}) {
  const [session, setSession] = useState<Session | null>(load);

  const signOut = useCallback(() => {
    save(null);
    setSession(null);
  }, []);

  const api = useMemo(
    () => createApi(apiBase, () => session?.token ?? null, signOut, fetchImpl),
    [apiBase, session?.token, signOut, fetchImpl],
  );

  const signIn = useCallback(
    async (token: string) => {
      const probe = createApi(apiBase, () => token, () => {}, fetchImpl);
      const me = await probe.get<Me>("/admin/me");
      const next = { token, me };
      save(next);
      setSession(next);
    },
    [apiBase, fetchImpl],
  );

  const value = useMemo<AuthState>(
    () => ({
      api,
      me: session?.me ?? null,
      pollMs,
      signIn,
      signOut,
      can: (minimum) => !!session && RANK[session.me.admin_role as AdminRole] >= RANK[minimum],
    }),
    [api, session, pollMs, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

/** Renders children only for admins with at least `role`. Hiding is a courtesy; the API enforces. */
export function RequireRole({ role, children }: { role: AdminRole; children: ReactNode }) {
  return useAuth().can(role) ? <>{children}</> : null;
}
