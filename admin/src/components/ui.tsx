import { type ReactNode, useEffect, useRef } from "react";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import type { Job, ModuleChange, ReleaseStatus } from "../api/types";
import { humanize } from "../format";

type Tone = "ok" | "warn" | "crit" | "info" | "accent" | "neutral";

export function Pill({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`pill ${tone === "neutral" ? "" : tone}`}>
      <span className="dot" aria-hidden="true" />
      {children}
    </span>
  );
}

const RELEASE_TONE: Record<ReleaseStatus, Tone> = {
  draft: "info",
  building: "accent",
  gate: "accent",
  awaiting_confirmation: "warn",
  live: "ok",
  superseded: "neutral",
  failed: "crit",
};

export function ReleaseStatusPill({ status }: { status: ReleaseStatus }) {
  return <Pill tone={RELEASE_TONE[status]}>{humanize(status)}</Pill>;
}

export function OutcomePill({ outcome }: { outcome: string | null | undefined }) {
  if (!outcome) return <Pill>in progress</Pill>;
  const tone: Tone = outcome === "answer" ? "ok" : outcome.includes("restricted") ? "warn" : outcome === "error" ? "crit" : "neutral";
  return <Pill tone={tone}>{humanize(outcome.replace("refusal:", ""))}</Pill>;
}

export function Modules({ modules }: { modules: string[] | null | undefined }) {
  if (!modules?.length) return <span className="muted">–</span>;
  return (
    <span className="chips">
      {modules.map((m) => (
        <span key={m} className="chip">
          {m}
        </span>
      ))}
    </span>
  );
}

/** before → after, with dropped modules struck through (they widen access). */
export function ModuleDelta({ change }: { change: ModuleChange }) {
  const before = change.before ?? [];
  const after = change.after ?? [];
  return (
    <span className="chips">
      {before.filter((m) => !after.includes(m)).map((m) => (
        <span key={`-${m}`} className="chip drop" title="dropped: more users can see this">
          {m}
        </span>
      ))}
      {after.map((m) => (
        <span key={m} className={`chip ${before.includes(m) || !change.before ? "" : "add"}`}>
          {m}
        </span>
      ))}
    </span>
  );
}

export function Tile({ k, v, d, href, attention }: { k: string; v: ReactNode; d?: ReactNode; href?: string; attention?: boolean }) {
  const body = (
    <>
      <span className="k">{k}</span>
      <span className="v">{v}</span>
      {d && <span className="d">{d}</span>}
    </>
  );
  const cls = `tile${attention ? " attention" : ""}`;
  return href ? (
    <Link className={cls} to={href}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

export function ErrorNotice({ error }: { error: Error | undefined }) {
  if (!error) return null;
  const details = error instanceof ApiError ? error.details : [error.message];
  const forbidden = error instanceof ApiError && error.status === 403;
  return (
    <div className="notice err" role="alert">
      {forbidden ? "Your role can't do that." : details.length > 1 ? "There were problems:" : details[0]}
      {!forbidden && details.length > 1 && (
        <ul>
          {details.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <div className="empty" aria-busy="true">
      {what}…
    </div>
  );
}

export function JobProgress({ job }: { job: Job | undefined }) {
  if (!job) return null;
  const pct = job.progress.pct;
  return (
    <div className="card" aria-live="polite">
      <div className="card-head">
        <strong>{humanize(job.kind)}</strong>
        <span className="muted">
          {job.status === "failed" ? `failed: ${job.error ?? "unknown error"}` : `${humanize(job.progress.stage)} · ${pct}%`}
        </span>
      </div>
      <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Job progress">
        <div style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/** A native <dialog> that opens while `open` is true. */
export function Dialog({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      if (typeof d.showModal === "function") d.showModal();
      else d.setAttribute("open", "");
    }
    if (!open && d.open) {
      if (typeof d.close === "function") d.close();
      else d.removeAttribute("open");
    }
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} aria-label={title}>
      {open && (
        <div className="dlg">
          <h2>{title}</h2>
          {children}
        </div>
      )}
    </dialog>
  );
}

export function PageHead({ title, sub, crumbs, actions }: { title: string; sub?: ReactNode; crumbs?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        {crumbs && <div className="crumbs">{crumbs}</div>}
        <h1>{title}</h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
      {actions && <div className="toolbar">{actions}</div>}
    </header>
  );
}
