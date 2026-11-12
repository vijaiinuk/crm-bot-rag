import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { useAction, useJob, useResource } from "../api/hooks";
import type { EvalQuestion, EvalQuestionCreate, EvalResult, EvalRun, EvalRunDetail, Expected, RunAccepted } from "../api/types";
import { RequireRole, useAuth } from "../auth";
import { Dialog, ErrorNotice, JobProgress, Loading, PageHead, Pill } from "../components/ui";
import { ago, humanize, money, pct, when } from "../format";

const OUTCOMES: Expected["outcome"][] = ["answer", "restricted", "not_found", "out_of_scope"];
const CATEGORIES: EvalQuestionCreate["category"][] = ["single", "multi_hop", "unanswerable", "out_of_scope", "restricted", "adversarial"];
const STATUS_TONE = { accepted: "ok", proposed: "warn", rejected: "neutral" } as const;

export function Evals() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "runs" ? "runs" : "questions";
  return (
    <>
      <PageHead
        title="Evals"
        sub="Questions with expected outcomes per persona. Retrieval and permission checks run on every publish; end-to-end runs are manual."
      />
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "questions"} onClick={() => setParams({})}>
          Questions
        </button>
        <button type="button" role="tab" aria-selected={tab === "runs"} onClick={() => setParams({ tab: "runs" })}>
          End-to-end runs
        </button>
      </div>
      {tab === "questions" ? <Questions /> : <Runs />}
    </>
  );
}

function summarize(e: Expected): string {
  if (e.outcome === "answer") return `answer from ${(e.required ?? []).join(", ") || "any section"}`;
  if (e.outcome === "restricted") return `restricted (missing ${(e.missing_modules ?? []).join(", ")})`;
  return humanize(e.outcome);
}

function Questions() {
  const { api } = useAuth();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const { data, error, reload } = useResource<EvalQuestion[]>(`/admin/eval-questions${status ? `?status=${status}` : ""}`);
  const [editing, setEditing] = useState<EvalQuestion | "new" | null>(null);
  const review = useAction(async (id: string, accept: boolean) => {
    await api.post(`/admin/eval-questions/${id}/${accept ? "accept" : "reject"}`);
    reload();
  });

  // Deep link from a failed gate: /evals?q=q-0001 opens that question for editing.
  const deepLink = params.get("q");
  useEffect(() => {
    if (!deepLink) return;
    api.get<EvalQuestion>(`/admin/eval-questions/${encodeURIComponent(deepLink)}`).then(setEditing, () => {});
  }, [api, deepLink]);

  const personas = useMemo(() => [...new Set((data ?? []).flatMap((q) => Object.keys(q.expected)))].sort(), [data]);

  return (
    <>
      <div className="toolbar">
        <label className="toolbar">
          Status
          <select value={status} onChange={(e) => setParams(e.target.value ? { status: e.target.value } : {})} aria-label="Filter by status">
            <option value="">All</option>
            <option value="proposed">Proposed</option>
            <option value="accepted">Accepted</option>
            <option value="rejected">Rejected</option>
          </select>
        </label>
        <span className="muted">{data ? `${data.length} questions` : ""}</span>
        <span style={{ flex: 1 }} />
        <RequireRole role="editor">
          <button type="button" className="btn primary" onClick={() => setEditing("new")}>
            Add question
          </button>
        </RequireRole>
      </div>
      <ErrorNotice error={error ?? review.error} />
      {!data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Question</th>
                <th>Expected per persona</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.map((q) => (
                <tr key={q.id}>
                  <td>
                    {q.question}
                    <div className="muted">
                      <code>{q.id}</code> · {humanize(q.category)} · {q.source}
                    </div>
                  </td>
                  <td>
                    {Object.entries(q.expected).map(([p, e]) => (
                      <div key={p}>
                        <code>{p}</code>: <span className="muted">{summarize(e)}</span>
                      </div>
                    ))}
                  </td>
                  <td>
                    <Pill tone={STATUS_TONE[q.status]}>{q.status}</Pill>
                  </td>
                  <td>
                    <RequireRole role="editor">
                      <span className="toolbar">
                        {q.status === "proposed" && (
                          <>
                            <button type="button" className="btn small" onClick={() => review.run(q.id, true)} disabled={review.busy}>
                              Accept
                            </button>
                            <button type="button" className="btn small danger" onClick={() => review.run(q.id, false)} disabled={review.busy}>
                              Reject
                            </button>
                          </>
                        )}
                        <button type="button" className="btn small" onClick={() => setEditing(q)}>
                          Edit
                        </button>
                      </span>
                    </RequireRole>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <QuestionDialog
        question={editing}
        personas={personas}
        onClose={() => {
          setEditing(null);
          if (deepLink) setParams({});
        }}
        onSaved={() => {
          setEditing(null);
          if (deepLink) setParams({});
          reload();
        }}
      />
    </>
  );
}

function QuestionDialog({
  question,
  personas,
  onClose,
  onSaved,
}: {
  question: EvalQuestion | "new" | null;
  personas: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { api } = useAuth();
  const isNew = question === "new";
  const [text, setText] = useState("");
  const [category, setCategory] = useState<EvalQuestionCreate["category"]>("single");
  const [expected, setExpected] = useState<Record<string, Expected>>({});

  useEffect(() => {
    if (question === null) return;
    if (question === "new") {
      setText("");
      setCategory("single");
      setExpected(Object.fromEntries(personas.map((p) => [p, { outcome: "answer", required: [], missing_modules: [] } as Expected])));
    } else {
      setText(question.question);
      setCategory(question.category);
      setExpected(structuredClone(question.expected));
    }
  }, [question, personas]);

  const save = useAction(async () => {
    const body = { question: text, category, expected };
    if (isNew) await api.post("/admin/eval-questions", body);
    else if (question) await api.patch(`/admin/eval-questions/${question.id}`, body);
    onSaved();
  });

  function update(persona: string, patch: Partial<Expected>) {
    setExpected((e) => ({ ...e, [persona]: { ...e[persona]!, ...patch } }));
  }
  const list = (v: string) => v.split(/[\s,]+/).filter(Boolean);

  return (
    <Dialog
      open={question !== null}
      onClose={() => {
        save.clearError();
        onClose();
      }}
      title={typeof question === "object" && question ? `Edit ${question.id}` : "Add an eval question"}
    >
      <form
        style={{ display: "grid", gap: 12 }}
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void save.run();
        }}
      >
        <label className="field">
          <span>Question, as a user would ask it</span>
          <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} required minLength={5} />
        </label>
        <label className="field">
          <span>Category</span>
          <select value={category} onChange={(e) => setCategory(e.target.value as EvalQuestionCreate["category"])}>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {humanize(c)}
              </option>
            ))}
          </select>
        </label>
        {Object.entries(expected).map(([p, e]) => (
          <fieldset key={p} style={{ border: "1px solid var(--line)", borderRadius: 8, display: "grid", gap: 8 }}>
            <legend>
              <code>{p}</code>
            </legend>
            <label className="field">
              <span>Expected outcome</span>
              <select value={e.outcome} onChange={(ev) => update(p, { outcome: ev.target.value as Expected["outcome"] })}>
                {OUTCOMES.map((o) => (
                  <option key={o} value={o}>
                    {humanize(o)}
                  </option>
                ))}
              </select>
            </label>
            {e.outcome === "answer" && (
              <label className="field">
                <span>Sections the answer must come from (doc_id#anchor, one per line)</span>
                <textarea rows={2} className="mono" value={(e.required ?? []).join("\n")} onChange={(ev) => update(p, { required: list(ev.target.value) })} />
              </label>
            )}
            {e.outcome === "restricted" && (
              <label className="field">
                <span>Modules this persona is missing</span>
                <input type="text" value={(e.missing_modules ?? []).join(", ")} onChange={(ev) => update(p, { missing_modules: list(ev.target.value) })} />
              </label>
            )}
          </fieldset>
        ))}
        <ErrorNotice error={save.error} />
        <div className="dlg-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={save.busy}>
            Save
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function Runs() {
  const { api } = useAuth();
  const navigate = useNavigate();
  const { data, error, reload } = useResource<EvalRun[]>("/admin/eval-runs");
  const [started, setStarted] = useState<RunAccepted | null>(null);
  const job = useJob(started?.job_id ?? null, () => {
    reload();
    if (started) navigate(`/evals/runs/${started.run_id}`);
  });
  const start = useAction(async () => setStarted(await api.post<RunAccepted>("/admin/eval-runs")));
  const running = data?.some((r) => r.status === "running");

  return (
    <>
      <div className="toolbar">
        <span className="muted">Each run answers every accepted question for each persona, then an LLM judge scores the answers. It costs money.</span>
        <span style={{ flex: 1 }} />
        <RequireRole role="publisher">
          <button type="button" className="btn primary" onClick={() => start.run()} disabled={start.busy || !!started || running}>
            Run end-to-end evals
          </button>
        </RequireRole>
      </div>
      <ErrorNotice error={error ?? start.error} />
      {job && <JobProgress job={job} />}
      {!data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Run</th>
                <th>Release</th>
                <th className="num">Faithfulness</th>
                <th className="num">Correctness</th>
                <th className="num">Refusals</th>
                <th className="num">Citations</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id} className="clickable" onClick={() => navigate(`/evals/runs/${r.id}`)}>
                  <td>
                    <Link to={`/evals/runs/${r.id}`} onClick={(e) => e.stopPropagation()}>
                      {r.id}
                    </Link>{" "}
                    {r.status !== "succeeded" && <Pill tone={r.status === "failed" ? "crit" : "accent"}>{r.status}</Pill>}
                    <div className="muted">
                      {ago(r.started_at)} · {r.started_by}
                    </div>
                  </td>
                  <td>{r.release_id ?? "–"}</td>
                  <td className="num">{pct(r.metrics?.faithfulness)}</td>
                  <td className="num">{pct(r.metrics?.correctness)}</td>
                  <td className="num">{pct(r.metrics?.refusal_accuracy)}</td>
                  <td className="num">{pct(r.metrics?.citation_accuracy)}</td>
                  <td className="num">{money(r.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

type ResultFilter = "all" | "unlabelled" | "disagree" | "wrong";

export function EvalRunView() {
  const { runId = "" } = useParams();
  const { api } = useAuth();
  const { data: run, error, reload } = useResource<EvalRunDetail>(`/admin/eval-runs/${encodeURIComponent(runId)}`);
  const [filter, setFilter] = useState<ResultFilter>("all");
  const label = useAction(async (r: EvalResult, faithful: boolean, correct: boolean) => {
    await api.put(`/admin/eval-results/${encodeURIComponent(r.id)}/label`, { faithful, correct });
    reload();
  });

  if (error) return <ErrorNotice error={error} />;
  if (!run) return <Loading />;
  const m = run.metrics;
  const agree = run.judge_agreement;
  const results = run.results.filter((r) =>
    filter === "unlabelled"
      ? !r.label
      : filter === "disagree"
        ? !!r.label && (r.label.faithful !== r.judge_faithful || r.label.correct !== r.judge_correct)
        : filter === "wrong"
          ? r.actual_outcome !== r.expected_outcome || !r.judge_correct
          : true,
  );

  return (
    <>
      <PageHead
        crumbs={<Link to="/evals?tab=runs">End-to-end runs</Link>}
        title={`Eval run ${run.id}`}
        sub={`${when(run.started_at)} · release ${run.release_id ?? "–"} · answer model ${run.answer_model} · judge ${run.judge_model} · ${money(run.cost_usd)}`}
      />
      <ErrorNotice error={label.error} />
      <div className="tiles">
        <div className="tile">
          <span className="k">Faithfulness</span>
          <span className="v">{pct(m?.faithfulness)}</span>
          <span className="d">answers supported by their sources</span>
        </div>
        <div className="tile">
          <span className="k">Correctness</span>
          <span className="v">{pct(m?.correctness)}</span>
        </div>
        <div className="tile">
          <span className="k">Refusal accuracy</span>
          <span className="v">{pct(m?.refusal_accuracy)}</span>
          <span className="d">restricted / not found handled right</span>
        </div>
        <div className="tile">
          <span className="k">Citation accuracy</span>
          <span className="v">{pct(m?.citation_accuracy)}</span>
        </div>
        <div className="tile" title="How often the LLM judge matches admin labels">
          <span className="k">Judge agreement</span>
          <span className="v">{pct(agree.faithful_agreement)}</span>
          <span className="d">
            faithfulness, over {agree.labelled} labelled · correctness {pct(agree.correct_agreement)}
          </span>
        </div>
      </div>
      {agree.labelled < 50 && (
        <div className="notice warn">
          Only {agree.labelled} answers are labelled. Label at least 50 before trusting the judge's scores.
        </div>
      )}
      <div className="toolbar">
        <label className="toolbar">
          Show
          <select value={filter} onChange={(e) => setFilter(e.target.value as ResultFilter)} aria-label="Filter results">
            <option value="all">All ({run.results.length})</option>
            <option value="unlabelled">Unlabelled</option>
            <option value="disagree">Judge and label disagree</option>
            <option value="wrong">Wrong outcome or incorrect</option>
          </select>
        </label>
      </div>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Question</th>
              <th>Persona</th>
              <th>Outcome</th>
              <th>Judge</th>
              <th>Your label</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={r.id} className={r.actual_outcome !== r.expected_outcome ? "flag" : undefined}>
                <td>
                  {r.question}
                  <div className="muted">{r.answer}</div>
                </td>
                <td>
                  <code>{r.persona}</code>
                </td>
                <td>
                  <Pill tone={r.actual_outcome === r.expected_outcome ? "ok" : "crit"}>{humanize(r.actual_outcome)}</Pill>
                  {r.actual_outcome !== r.expected_outcome && <div className="muted">expected {humanize(r.expected_outcome)}</div>}
                </td>
                <td>
                  <div>{r.judge_faithful ? "faithful" : <span style={{ color: "var(--crit)" }}>unfaithful</span>}</div>
                  <div>{r.judge_correct ? "correct" : <span style={{ color: "var(--crit)" }}>incorrect</span>}</div>
                </td>
                <td>
                  <LabelControls result={r} busy={label.busy} onLabel={(f, c) => label.run(r, f, c)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function LabelControls({ result, busy, onLabel }: { result: EvalResult; busy: boolean; onLabel: (faithful: boolean, correct: boolean) => void }) {
  const { can } = useAuth();
  const l = result.label;
  if (!can("editor")) return l ? <span>{`${l.faithful ? "faithful" : "unfaithful"}, ${l.correct ? "correct" : "incorrect"}`}</span> : <span className="muted">–</span>;
  const faithful = l?.faithful ?? result.judge_faithful;
  const correct = l?.correct ?? result.judge_correct;
  return (
    <div style={{ display: "grid", gap: 4 }}>
      <label className="toolbar">
        <input type="checkbox" checked={faithful} disabled={busy} onChange={(e) => onLabel(e.target.checked, correct)} /> faithful
      </label>
      <label className="toolbar">
        <input type="checkbox" checked={correct} disabled={busy} onChange={(e) => onLabel(faithful, e.target.checked)} /> correct
      </label>
      {l ? (
        <span className="muted" style={{ fontSize: 12 }}>
          by {l.labeller}
        </span>
      ) : (
        <button type="button" className="btn small" disabled={busy} onClick={() => onLabel(faithful, correct)}>
          Agree with judge
        </button>
      )}
    </div>
  );
}
