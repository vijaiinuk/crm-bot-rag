import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { useResource } from "../api/hooks";
import type { ConversationDetail, ConversationSummary } from "../api/types";
import { ErrorNotice, Loading, OutcomePill, PageHead } from "../components/ui";
import { ago, int, money, when } from "../format";

export function Conversations() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const tenant = params.get("tenant") ?? "";
  const sort = params.get("sort") === "cost" ? "cost" : "recent";
  const query = new URLSearchParams({ sort, limit: "100", ...(tenant ? { tenant } : {}) });
  const { data, error } = useResource<ConversationSummary[]>(`/admin/conversations?${query}`);

  function set(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  }

  return (
    <>
      <PageHead title="Conversations" sub="Chat sessions from client users. Messages are redacted before they're stored and kept for 30 days." />
      <div className="toolbar">
        <label className="toolbar">
          Client
          <select value={tenant} onChange={(e) => set("tenant", e.target.value)} aria-label="Filter by client">
            <option value="">All</option>
            <option value="acme">acme</option>
            <option value="globex">globex</option>
          </select>
        </label>
        <label className="toolbar">
          Sort by
          <select value={sort} onChange={(e) => set("sort", e.target.value === "cost" ? "cost" : "")} aria-label="Sort">
            <option value="recent">Most recent</option>
            <option value="cost">Highest cost</option>
          </select>
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
                <th>Last active</th>
                <th>Client</th>
                <th>User</th>
                <th className="num">Turns</th>
                <th>Last outcome</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.conversation_id} className="clickable" onClick={() => navigate(`/conversations/${c.conversation_id}`)}>
                  <td>
                    <Link to={`/conversations/${c.conversation_id}`} onClick={(e) => e.stopPropagation()}>
                      {ago(c.last_active_at)}
                    </Link>
                  </td>
                  <td>{c.tenant}</td>
                  <td>
                    {c.sub}
                    <div className="muted">{c.role}</div>
                  </td>
                  <td className="num">{c.turns}</td>
                  <td>
                    <OutcomePill outcome={c.last_outcome} />
                  </td>
                  <td className="num">{money(c.cost_usd)}</td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td colSpan={6} className="empty">
                    No conversations.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function ConversationView() {
  const { conversationId = "" } = useParams();
  const { data: c, error } = useResource<ConversationDetail>(`/admin/conversations/${encodeURIComponent(conversationId)}`);
  if (error) return <ErrorNotice error={error} />;
  if (!c) return <Loading />;

  const byTrace = new Map<string, number>();
  for (const call of c.llm_calls) byTrace.set(call.trace_id, (byTrace.get(call.trace_id) ?? 0) + call.cost_usd);

  return (
    <>
      <PageHead
        crumbs={<Link to="/conversations">Conversations</Link>}
        title={`${c.tenant} · ${c.sub}`}
        sub={`${c.role} · started ${when(c.created_at)} · ${c.turns} turn(s) · ${money(c.cost_usd)} estimated`}
      />
      <div className="card">
        <h2>Transcript</h2>
        <p className="muted" style={{ margin: 0 }}>
          Redacted at storage time: emails, phone numbers and long numbers are replaced with placeholders.
        </p>
        <div className="transcript">
          {c.messages.map((m) => (
            <div key={m.id} className={`bubble ${m.role}`}>
              {m.content}
              <div className="meta">
                <span>{when(m.created_at)}</span>
                {m.role === "assistant" && (
                  <>
                    <OutcomePill outcome={m.outcome} />
                    <span>{byTrace.has(m.trace_id) ? money(byTrace.get(m.trace_id) ?? 0) : "no LLM call"}</span>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="card">
        <h2>LLM calls</h2>
        {c.llm_calls.length === 0 ? (
          <p className="muted">No LLM calls: every answer was a templated refusal.</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Stage</th>
                  <th>Model</th>
                  <th className="num">Input</th>
                  <th className="num">Cached</th>
                  <th className="num">Output</th>
                  <th className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {c.llm_calls.map((call) => (
                  <tr key={call.id}>
                    <td>{when(call.created_at)}</td>
                    <td>{call.stage}</td>
                    <td>
                      <code>{call.model_id}</code>
                    </td>
                    <td className="num">{int(call.input_tokens)}</td>
                    <td className="num">{int(call.cached_input_tokens)}</td>
                    <td className="num">{int(call.output_tokens)}</td>
                    <td className="num">{money(call.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
