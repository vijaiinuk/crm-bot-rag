import { type FormEvent, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { useAction, useJob, useResource } from "../api/hooks";
import type { DocumentDetail, DocumentSummary, DocumentVersion, DocumentVersionContent, JobAccepted } from "../api/types";
import { RequireRole, useAuth } from "../auth";
import { Dialog, ErrorNotice, JobProgress, Loading, Modules, PageHead, Pill } from "../components/ui";
import { ago, day, int, when } from "../format";

export function Documents() {
  const [staleDays, setStaleDays] = useState(90);
  const [query, setQuery] = useState("");
  const [onlyStale, setOnlyStale] = useState(false);
  const [uploading, setUploading] = useState(false);
  const { data, error, reload } = useResource<DocumentSummary[]>(`/admin/documents?stale_days=${staleDays}`);
  const navigate = useNavigate();

  const rows = useMemo(
    () =>
      (data ?? []).filter(
        (d) =>
          (!onlyStale || d.stale) &&
          (query === "" || `${d.doc_id} ${d.title}`.toLowerCase().includes(query.toLowerCase())),
      ),
    [data, query, onlyStale],
  );
  const staleCount = data?.filter((d) => d.stale).length ?? 0;

  return (
    <>
      <PageHead
        title="Documents"
        sub="Every uploaded doc and its versions. Modules come from each doc's frontmatter."
        actions={
          <RequireRole role="editor">
            <button type="button" className="btn primary" onClick={() => setUploading(true)}>
              Upload markdown
            </button>
          </RequireRole>
        }
      />
      <div className="toolbar">
        <input type="search" placeholder="Filter by id or title" aria-label="Filter documents" value={query} onChange={(e) => setQuery(e.target.value)} />
        <label className="toolbar">
          <input type="checkbox" checked={onlyStale} onChange={(e) => setOnlyStale(e.target.checked)} /> Stale only ({staleCount})
        </label>
        <label className="toolbar">
          Stale after
          <input
            type="number"
            min={1}
            max={3650}
            value={staleDays}
            style={{ width: 80 }}
            aria-label="Stale after days"
            onChange={(e) => setStaleDays(Math.min(3650, Math.max(1, Number(e.target.value) || 90)))}
          />
          days
        </label>
      </div>
      <ErrorNotice error={error} />
      {!data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Document</th>
                <th>Modules</th>
                <th className="num">Live</th>
                <th className="num">Draft</th>
                <th className="num">Latest</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.doc_id} className="clickable" onClick={() => navigate(`/documents/${d.doc_id}`)}>
                  <td>
                    <Link to={`/documents/${d.doc_id}`} onClick={(e) => e.stopPropagation()}>
                      {d.title}
                    </Link>
                    <div className="muted mono">{d.doc_id}</div>
                  </td>
                  <td>
                    <Modules modules={d.modules} />
                  </td>
                  <td className="num">{d.live_version ? `v${d.live_version}` : <span className="muted">–</span>}</td>
                  <td className="num">
                    {d.draft_version ? `v${d.draft_version}` : <span className="muted">–</span>}
                    {d.draft_version && d.draft_version !== d.live_version && <Pill tone="info">changed</Pill>}
                  </td>
                  <td className="num">
                    v{d.latest_version} {d.latest_status === "rejected" && <Pill tone="crit">rejected</Pill>}
                  </td>
                  <td>
                    {ago(d.updated_at)} {d.stale && <Pill tone="warn">stale</Pill>}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="empty">
                    No documents match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <UploadDialog
        open={uploading}
        onClose={() => setUploading(false)}
        onUploaded={() => {
          reload();
        }}
      />
    </>
  );
}

function UploadDialog({ open, onClose, onUploaded }: { open: boolean; onClose: () => void; onUploaded: () => void }) {
  const { api } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<DocumentVersion>();
  const upload = useAction((f: File) => api.upload<DocumentVersion>("/admin/documents", f));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const v = await upload.run(file);
    if (v) {
      setResult(v);
      onUploaded();
    }
  }

  function close() {
    setFile(null);
    setResult(undefined);
    upload.clearError();
    onClose();
  }

  return (
    <Dialog open={open} onClose={close} title="Upload a markdown document">
      <p className="muted" style={{ margin: 0 }}>
        The file needs frontmatter with <code>doc_id</code>, <code>title</code> and <code>modules</code>. Re-uploading a{" "}
        <code>doc_id</code> adds a new version; nothing goes live until a release is published.
      </p>
      <form onSubmit={submit} style={{ display: "grid", gap: 12 }}>
        <label className="field">
          <span>Markdown file</span>
          <input type="file" accept=".md,.markdown,text/markdown" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <ErrorNotice error={upload.error} />
        {result && (
          <div className={`notice ${result.status === "validated" ? "ok" : "err"}`} role="status">
            {result.status === "validated" ? (
              <>
                Uploaded <strong>{result.doc_id}</strong> v{result.version}. Add it to the draft release from the document page.
              </>
            ) : (
              <>
                {result.doc_id} v{result.version} was stored but <strong>rejected</strong>:
                <ul>
                  {result.validation_errors.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
        <div className="dlg-actions">
          <button type="button" className="btn" onClick={close}>
            {result ? "Done" : "Cancel"}
          </button>
          <button type="submit" className="btn primary" disabled={!file || upload.busy}>
            {upload.busy ? "Uploading…" : "Upload"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function DocumentView() {
  const { docId = "" } = useParams();
  const { api } = useAuth();
  const { data: doc, error, reload } = useResource<DocumentDetail>(`/admin/documents/${encodeURIComponent(docId)}`);
  const [viewing, setViewing] = useState<number>();
  const content = useResource<DocumentVersionContent>(
    viewing ? `/admin/documents/${encodeURIComponent(docId)}/versions/${viewing}` : null,
  );
  const [jobId, setJobId] = useState<string | null>(null);
  const [synthDone, setSynthDone] = useState(false);
  const job = useJob(jobId, () => setSynthDone(true));

  const pinVersion = useAction(async (version: number) => {
    await api.put(`/admin/releases/draft/documents/${encodeURIComponent(docId)}`, { version });
    reload();
  });
  const removeFromDraft = useAction(async () => {
    await api.del(`/admin/releases/draft/documents/${encodeURIComponent(docId)}`);
    reload();
  });
  const synth = useAction(async () => {
    setSynthDone(false);
    const r = await api.post<JobAccepted>(`/admin/documents/${encodeURIComponent(docId)}/synthetic-questions`);
    setJobId(r.job_id);
  });

  if (error) return <ErrorNotice error={error} />;
  if (!doc) return <Loading />;

  return (
    <>
      <PageHead
        crumbs={<Link to="/documents">Documents</Link>}
        title={doc.title}
        sub={
          <span className="toolbar">
            <code>{doc.doc_id}</code> <Modules modules={doc.modules} /> {doc.stale && <Pill tone="warn">stale</Pill>}
          </span>
        }
        actions={
          <RequireRole role="editor">
            <button type="button" className="btn" onClick={() => synth.run()} disabled={synth.busy || (!!job && !synthDone)}>
              Propose eval questions
            </button>
            {doc.draft_version && (
              <button type="button" className="btn danger" onClick={() => removeFromDraft.run()} disabled={removeFromDraft.busy}>
                Remove from draft
              </button>
            )}
          </RequireRole>
        }
      />
      <ErrorNotice error={pinVersion.error ?? removeFromDraft.error ?? synth.error} />
      {job && <JobProgress job={job} />}
      {synthDone && (
        <div className="notice ok">
          Proposed questions are ready for review in <Link to="/evals?status=proposed">Evals</Link>.
        </div>
      )}

      <div className="tiles">
        <div className="tile">
          <span className="k">Live</span>
          <span className="v">{doc.live_version ? `v${doc.live_version}` : "–"}</span>
          <span className="d">{doc.live_uploaded_at ? `uploaded ${day(doc.live_uploaded_at)}` : "not in the live release"}</span>
        </div>
        <div className="tile">
          <span className="k">Draft</span>
          <span className="v">{doc.draft_version ? `v${doc.draft_version}` : "–"}</span>
          <span className="d">{doc.draft_version ? "goes live with the next release" : "not in the draft"}</span>
        </div>
        <div className="tile">
          <span className="k">Versions</span>
          <span className="v">{doc.versions.length}</span>
          <span className="d">latest {ago(doc.updated_at)}</span>
        </div>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th className="num">Version</th>
              <th>Status</th>
              <th>Modules</th>
              <th className="num">Sections</th>
              <th>Uploaded</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {[...doc.versions].reverse().map((v) => (
              <tr key={v.version}>
                <td className="num">
                  v{v.version}
                  {v.version === doc.live_version && <> <Pill tone="ok">live</Pill></>}
                  {v.version === doc.draft_version && <> <Pill tone="info">draft</Pill></>}
                </td>
                <td>
                  {v.status === "validated" ? <Pill tone="ok">validated</Pill> : <Pill tone="crit">rejected</Pill>}
                  {v.validation_errors.length > 0 && (
                    <ul className="muted" style={{ margin: "6px 0 0", paddingLeft: 16 }}>
                      {v.validation_errors.map((e) => (
                        <li key={e}>{e}</li>
                      ))}
                    </ul>
                  )}
                </td>
                <td>
                  <Modules modules={v.modules} />
                </td>
                <td className="num">{int(v.anchors.length)}</td>
                <td>
                  {when(v.uploaded_at)}
                  <div className="muted">{v.uploaded_by}</div>
                </td>
                <td>
                  <span className="toolbar">
                    <button type="button" className="btn small" onClick={() => setViewing(viewing === v.version ? undefined : v.version)}>
                      {viewing === v.version ? "Hide" : "View"}
                    </button>
                    <RequireRole role="editor">
                      {v.status === "validated" && v.version !== doc.draft_version && (
                        <button type="button" className="btn small" onClick={() => pinVersion.run(v.version)} disabled={pinVersion.busy}>
                          Use in draft
                        </button>
                      )}
                    </RequireRole>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {viewing && (
        <div className="card">
          <h2>
            {doc.doc_id} v{viewing}
          </h2>
          {content.data ? <pre className="markdown">{content.data.markdown}</pre> : <Loading />}
        </div>
      )}
    </>
  );
}
