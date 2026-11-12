// Dev sign-in: picks one of the local admins and mints a token from the API's
// local-only /dev/admin-token. Production replaces this page with the CRM's SSO.

import { useEffect, useState } from "react";

import { useAuth } from "../auth";
import { ErrorNotice } from "../components/ui";

interface DevToken {
  token: string;
}

const BLURB: Record<string, string> = {
  viewer: "Read everything, change nothing.",
  editor: "Upload docs, shape the draft release, write and label evals.",
  publisher: "Everything an editor can do, plus publish, confirm and roll back releases and run end-to-end evals.",
};

export function SignIn() {
  const { api, signIn } = useAuth();
  const [admins, setAdmins] = useState<Record<string, string>>();
  const [error, setError] = useState<Error>();
  const [busy, setBusy] = useState<string>();

  useEffect(() => {
    api.get<Record<string, string>>("/dev/admins").then(setAdmins, (e: Error) =>
      setError(new Error(`Can't reach the API at ${api.base} (${e.message}). Is \`make run\` going?`)),
    );
  }, [api]);

  async function choose(admin: string) {
    setBusy(admin);
    setError(undefined);
    try {
      const { token } = await api.post<DevToken>("/dev/admin-token", { admin });
      await signIn(token);
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(undefined);
    }
  }

  return (
    <main className="main" style={{ maxWidth: 560, margin: "8vh auto" }}>
      <div className="card">
        <div>
          <h1>Help Bot Admin</h1>
          <p className="muted" style={{ margin: "6px 0 0" }}>
            Development sign-in. Pick a role; production uses the CRM's single sign-on instead.
          </p>
        </div>
        <ErrorNotice error={error} />
        {admins && (
          <div style={{ display: "grid", gap: 8 }}>
            {Object.entries(admins).map(([admin, role]) => (
              <button
                key={admin}
                type="button"
                className="btn"
                style={{ justifyContent: "space-between", padding: "12px 14px", textAlign: "left" }}
                disabled={!!busy}
                onClick={() => choose(admin)}
              >
                <span>
                  <strong>Sign in as {role}</strong>
                  <br />
                  <span className="muted">{BLURB[role] ?? admin}</span>
                </span>
                <span className="muted">{busy === admin ? "…" : admin}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
