import { useState } from "react";
import { Link } from "react-router";

import { useResource } from "../api/hooks";
import type { CostSummary, ModelPrice } from "../api/types";
import { CostChart } from "../components/CostChart";
import { ErrorNotice, Loading, PageHead, Tile } from "../components/ui";
import { int, money } from "../format";

const PERIODS = [7, 30, 60, 90];

export function Costs() {
  const [days, setDays] = useState(30);
  const { data: s, error } = useResource<CostSummary>(`/admin/costs?days=${days}`);
  const { data: prices } = useResource<ModelPrice[]>("/admin/prices");

  const tenants = s ? [...new Set(s.by_tenant_month.map((t) => t.tenant))].sort() : [];
  const months = s ? [...new Set(s.by_tenant_month.map((t) => t.month))].sort() : [];
  const cell = (tenant: string, month: string) => s?.by_tenant_month.find((t) => t.tenant === tenant && t.month === month);

  return (
    <>
      <PageHead
        title="LLM costs"
        sub="Estimated from token counts and the price in effect at each call. Placeholder prices until the model bake-off."
        actions={
          <label className="toolbar">
            Period
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period">
              {PERIODS.map((d) => (
                <option key={d} value={d}>
                  Last {d} days
                </option>
              ))}
            </select>
          </label>
        }
      />
      <ErrorNotice error={error} />
      {!s ? (
        <Loading />
      ) : (
        <>
          <div className="tiles">
            <Tile k="Total" v={money(s.total_usd)} d={`${s.start} to ${s.end}`} />
            <Tile k="Chat (billable to clients)" v={money(s.by_bucket.chat ?? 0)} />
            <Tile k="Evals (internal)" v={money(s.by_bucket.eval ?? 0)} d="end-to-end runs and the judge" />
            <Tile k="Ingest (internal)" v={money(s.by_bucket.ingest ?? 0)} d="synthetic question generation" />
          </div>
          <div className="card">
            <h2>Daily cost</h2>
            <CostChart daily={s.daily} />
          </div>
          <div className="grid-2">
            <div className="card">
              <h2>By client company</h2>
              {tenants.length === 0 ? (
                <p className="muted">No client chat in this period.</p>
              ) : (
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Client</th>
                        {months.map((m) => (
                          <th key={m} className="num">
                            {m}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {tenants.map((t) => (
                        <tr key={t}>
                          <td>
                            <Link to={`/conversations?tenant=${t}`}>{t}</Link>
                          </td>
                          {months.map((m) => {
                            const c = cell(t, m);
                            return (
                              <td key={m} className="num">
                                {c ? money(c.cost_usd) : "–"}
                                {c && <div className="muted">{int(c.calls)} calls</div>}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div className="card">
              <h2>Most expensive sessions</h2>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Session</th>
                      <th>Client</th>
                      <th className="num">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.top_conversations.map((c) => (
                      <tr key={c.conversation_id}>
                        <td>
                          <Link to={`/conversations/${c.conversation_id}`} className="mono">
                            {c.conversation_id.slice(0, 8)}
                          </Link>
                        </td>
                        <td>{c.tenant}</td>
                        <td className="num">{money(c.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <div className="card">
            <h2>By model</h2>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th className="num">Calls</th>
                    <th className="num">Input tokens</th>
                    <th className="num">Output tokens</th>
                    <th className="num">Price per M tokens (in / out)</th>
                    <th className="num">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {s.by_model.map((m) => {
                    const p = prices?.find((x) => x.model_id === m.model_id);
                    return (
                      <tr key={m.model_id}>
                        <td>
                          <code>{m.model_id}</code>
                          {p?.note && <div className="muted">{p.note}</div>}
                        </td>
                        <td className="num">{int(m.calls)}</td>
                        <td className="num">{int(m.input_tokens)}</td>
                        <td className="num">{int(m.output_tokens)}</td>
                        <td className="num">{p ? `${money(p.input_per_mtok)} / ${money(p.output_per_mtok)}` : "–"}</td>
                        <td className="num">{money(m.cost_usd)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  );
}
