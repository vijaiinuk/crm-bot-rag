import { NavLink, Outlet } from "react-router";

import { useResource } from "../api/hooks";
import type { Overview } from "../api/types";
import { useAuth } from "../auth";
import { Pill } from "./ui";

export function Layout() {
  const { me, signOut, api } = useAuth();
  // Badges for work waiting on someone; refreshed when the layout mounts.
  const { data: overview } = useResource<Overview>("/admin/overview");
  const proposed = overview?.proposed_questions ?? 0;
  const awaiting = overview?.last_published?.status === "awaiting_confirmation" ? 1 : 0;

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <b>Help Bot Admin</b>
          <span>Docs · releases · evals · cost</span>
        </div>
        <nav className="nav" aria-label="Admin sections">
          <NavLink to="/" end>
            Overview
          </NavLink>
          <NavLink to="/documents">Documents</NavLink>
          <NavLink to="/releases">
            Releases {awaiting > 0 && <span className="count" aria-label="1 release awaiting confirmation">1</span>}
          </NavLink>
          <NavLink to="/evals">
            Evals {proposed > 0 && <span className="count" aria-label={`${proposed} proposed questions`}>{proposed}</span>}
          </NavLink>
          <NavLink to="/costs">Costs</NavLink>
          <NavLink to="/conversations">Conversations</NavLink>
        </nav>
        <div className="who">
          <div className="row">
            <span title={me?.sub}>{me?.sub}</span>
            <Pill tone="accent">{me?.admin_role}</Pill>
          </div>
          <div className="row">
            <span className="muted" style={{ fontSize: 12 }} title="API base">
              {api.base.replace(/^https?:\/\//, "")}
            </span>
            <button type="button" className="btn small" onClick={signOut}>
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
