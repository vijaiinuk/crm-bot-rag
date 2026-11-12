import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { useAction, useJob, useResource } from "../api/hooks";
import type { DraftDiff, ModuleChange, PublishAccepted, Release } from "../api/types";
import { RequireRole, useAuth } from "../auth";
import { Dialog, ErrorNotice, JobProgress, Loading, ModuleDelta, PageHead, Pill, ReleaseStatusPill } from "../components/ui";
import { ago, humanize, when } from "../format";

const CHANGE_TONE: Record<ModuleChange["change"], "ok" | "warn" | "info" | "crit" | "neutral"> = {
  widened: "warn",
  narrowed: "ok",
  new: "info",
  retired: "crit",
  unchanged: "neutral",
};

function ChangesTable({ changes, empty }: { changes: ModuleChange[]; empty: string }) {
  const shown = changes.filter((c) => c.change !== "unchanged");
  if (!shown.length) return <p className="muted">{empty}</p>;
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Document</th>
            <th>Access</th>
            <th>Modules</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((c) => (
            <tr key={c.doc_id} className={c.change === "widened" ? "flag" : undefined}>
              <td>
                <Link to={`/documents/${c.doc_id}`}>{c.doc_id}</Link>
              </td>
              <td>
                <Pill tone={CHANGE_TONE[c.change]}>{c.change}</Pill>
                {c.change === "widened" && <div className="muted">more users will see it</div>}
              </td>
              <td>
                <ModuleDelta change={c} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Orphans({ diff }: { diff: DraftDiff }) {
  if (!diff.orphaned_labels.length) return null;
  return (
    <div className="notice err">
      {diff.orphaned_labels.length} eval label(s) point at sections that won't exist in this release. Publishing will fail until they're
      fixed:
      <ul>
        {diff.orphaned_labels.map((o) => (
          <li key={`${o.question_id}-${o.label}`}>
            <Link to={`/evals?q=${o.question_id}`}>{o.question_id}</Link> → <code>{o.label}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Releases() {
  const { api } = useAuth();
  const navigate = useNavigate();
  const releases = useResource<Release[]>("/admin/releases");
  const diff = useResource<DraftDiff>("/admin/releases/draft/diff");
  const [publishing, setPublishing] = useState<{ jobId: string; releaseId: string } | null>(null);
  const job = useJob(publishing?.jobId ?? null, () => {
    if (publishing) navigate(`/releases/${publishing.releaseId}`);
  });
  const publish = useAction(async (id: string) => {
    const r = await api.post<PublishAccepted>(`/admin/releases/${id}/publish`);
    setPublishing({ jobId: r.job_id, releaseId: r.release_id });
  });

  const draft = releases.data?.find((r) => r.status === "draft");
  const building = releases.data?.some((r) => r.status === "building" || r.status === "gate");
  const history = releases.data?.filter((r) => r.status !== "draft") ?? [];
  const widened = diff.data?.module_changes.filter((c) => c.change === "widened").length ?? 0;

  return (
    <>
      <PageHead title="Releases" sub="Publishing builds a complete new index and runs the gate. Chat users only ever see the live release." />
      <ErrorNotice error={releases.error ?? diff.error ?? publish.error} />
      {job && <JobProgress job={job} />}

      {draft && diff.data && (
        <section className="card" aria-labelledby="draft-h">
          <div className="card-head">
            <div>
              <h2 id="draft-h">
                Draft {draft.id} <ReleaseStatusPill status="draft" />
              </h2>
              <div className="muted">{Object.keys(draft.documents).length} documents. Change versions from each document's page.</div>
            </div>
            <RequireRole role="publisher">
              <button
                type="button"
                className="btn primary"
                disabled={publish.busy || !!publishing || building}
                onClick={() => publish.run(draft.id)}
              >
                Publish {draft.id}
              </button>
            </RequireRole>
          </div>
          {widened > 0 && (
            <div className="notice warn">
              {widened} document(s) would become visible to more users. The release will wait for a publisher to confirm.
            </div>
          )}
          <Orphans diff={diff.data} />
          <h3>Changes compared with the live release</h3>
          <ChangesTable changes={diff.data.module_changes} empty="No documents added, removed or re-scoped." />
        </section>
      )}

      <section className="card" aria-labelledby="hist-h">
        <h2 id="hist-h">History</h2>
        {!releases.data ? (
          <Loading />
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Release</th>
                  <th>Status</th>
                  <th className="num">Docs</th>
                  <th>Published</th>
                  <th>Live since</th>
                </tr>
              </thead>
              <tbody>
                {history.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => navigate(`/releases/${r.id}`)}>
                    <td>
                      <Link to={`/releases/${r.id}`} onClick={(e) => e.stopPropagation()}>
                        {r.id}
                      </Link>
                    </td>
                    <td>
                      <ReleaseStatusPill status={r.status} />
                    </td>
                    <td className="num">{Object.keys(r.documents).length}</td>
                    <td>
                      {when(r.published_at)}
                      <div className="muted">{r.published_by}</div>
                    </td>
                    <td>{r.live_since ? ago(r.live_since) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

export function ReleaseView() {
  const { releaseId = "" } = useParams();
  const { api } = useAuth();
  const { data: r, error, reload } = useResource<Release>(`/admin/releases/${encodeURIComponent(releaseId)}`);
  const job = useJob(r && (r.status === "building" || r.status === "gate") ? (r.job_id ?? null) : null, () => reload());
  const [confirming, setConfirming] = useState(false);
  const [rollingBack, setRollingBack] = useState(false);
  const confirm = useAction(async () => {
    await api.post(`/admin/releases/${releaseId}/confirm`);
    setConfirming(false);
    reload();
  });
  const rollback = useAction(async () => {
    await api.post(`/admin/releases/${releaseId}/rollback`);
    setRollingBack(false);
    reload();
  });

  if (error) return <ErrorNotice error={error} />;
  if (!r) return <Loading />;
  const gate = r.gate_report;
  const widened = gate?.module_changes.filter((c) => c.change === "widened") ?? [];

  return (
    <>
      <PageHead
        crumbs={<Link to="/releases">Releases</Link>}
        title={`Release ${r.id}`}
        sub={
          <span className="toolbar">
            <ReleaseStatusPill status={r.status} />
            {r.published_by && (
              <span className="muted">
                published by {r.published_by} · {when(r.published_at)}
              </span>
            )}
            {r.confirmed_by && <span className="muted">· widening confirmed by {r.confirmed_by}</span>}
          </span>
        }
        actions={
          <RequireRole role="publisher">
            {r.status === "awaiting_confirmation" && (
              <button type="button" className="btn warn" onClick={() => setConfirming(true)}>
                Review and confirm
              </button>
            )}
            {r.status === "superseded" && (
              <button type="button" className="btn" onClick={() => setRollingBack(true)}>
                Roll back to {r.id}
              </button>
            )}
          </RequireRole>
        }
      />
      <ErrorNotice error={confirm.error ?? rollback.error} />
      {job && job.status !== "succeeded" && <JobProgress job={job} />}

      {gate && (
        <section className="card" aria-labelledby="gate-h">
          <h2 id="gate-h">Publish gate</h2>
          <div className="checks">
            {gate.checks.map((c) => (
              <div key={c.name} className={`check ${c.status}`}>
                <div>
                  <strong>{humanize(c.name)}</strong>
                  <div>
                    <Pill tone={c.status === "pass" ? "ok" : c.status === "fail" ? "crit" : "warn"}>{humanize(c.status)}</Pill>
                  </div>
                </div>
                <div>{c.detail}</div>
              </div>
            ))}
          </div>
          <Orphans diff={gate} />
          <h3>Access changes</h3>
          <ChangesTable changes={gate.module_changes} empty="No documents added, removed or re-scoped." />
        </section>
      )}

      <section className="card">
        <h2>Contents</h2>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Document</th>
                <th className="num">Version</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(r.documents)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([doc, v]) => (
                  <tr key={doc}>
                    <td>
                      <Link to={`/documents/${doc}`}>{doc}</Link>
                    </td>
                    <td className="num">v{v}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>

      <Dialog open={confirming} onClose={() => setConfirming(false)} title={`Confirm wider access for ${r.id}`}>
        <p style={{ margin: 0 }}>Publishing {r.id} lets more users see these documents. Your confirmation is recorded in the audit log.</p>
        <ChangesTable changes={widened} empty="" />
        <div className="dlg-actions">
          <button type="button" className="btn" onClick={() => setConfirming(false)}>
            Cancel
          </button>
          <button type="button" className="btn warn" onClick={() => confirm.run()} disabled={confirm.busy}>
            Confirm and make live
          </button>
        </div>
      </Dialog>
      <Dialog open={rollingBack} onClose={() => setRollingBack(false)} title={`Roll back to ${r.id}?`}>
        <p style={{ margin: 0 }}>Chat answers switch to {r.id}'s documents immediately. The current live release can be restored the same way.</p>
        <div className="dlg-actions">
          <button type="button" className="btn" onClick={() => setRollingBack(false)}>
            Cancel
          </button>
          <button type="button" className="btn primary" onClick={() => rollback.run()} disabled={rollback.busy}>
            Roll back
          </button>
        </div>
      </Dialog>
    </>
  );
}
