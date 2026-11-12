import { Link } from "react-router";

import { useResource } from "../api/hooks";
import type { CostSummary, Overview } from "../api/types";
import { CostChart } from "../components/CostChart";
import { ErrorNotice, Loading, PageHead, ReleaseStatusPill, Tile } from "../components/ui";
import { ago, money, pct } from "../format";

export function OverviewPage() {
  const { data: o, error } = useResource<Overview>("/admin/overview");
  const { data: costs } = useResource<CostSummary>("/admin/costs?days=30");
  if (error) return <ErrorNotice error={error} />;
  if (!o) return <Loading />;

  const awaiting = o.last_published?.status === "awaiting_confirmation";
  const failed = o.last_published?.status === "failed";
  const metrics = o.last_eval_run?.metrics;

  return (
    <>
      <PageHead title="Overview" sub="What's live, what needs a decision, and what it costs." />

      {(awaiting || failed) && o.last_published && (
        <div className={`notice ${awaiting ? "warn" : "err"}`}>
          Release <Link to={`/releases/${o.last_published.id}`}>{o.last_published.id}</Link>{" "}
          {awaiting ? "widens who can see some documents and is waiting for a publisher to confirm." : "failed its publish gate."}
        </div>
      )}

      <div className="tiles">
        <Tile
          k="Live release"
          v={o.live_release?.id ?? "none"}
          d={o.live_release?.live_since ? `since ${ago(o.live_release.live_since)}` : "nothing published yet"}
          href={o.live_release ? `/releases/${o.live_release.id}` : "/releases"}
        />
        <Tile
          k="Draft"
          v={o.draft_release.id}
          d={`${Object.keys(o.draft_release.documents).length} documents`}
          href="/releases"
        />
        <Tile
          k="Last publish"
          v={o.last_published ? <ReleaseStatusPill status={o.last_published.status} /> : "–"}
          d={o.last_published?.published_at ? `${o.last_published.id} · ${ago(o.last_published.published_at)}` : undefined}
          href={o.last_published ? `/releases/${o.last_published.id}` : undefined}
          attention={awaiting || failed}
        />
        <Tile
          k="Documents"
          v={o.documents}
          d={o.stale_documents ? `${o.stale_documents} not updated in 90 days` : "all recently updated"}
          href="/documents"
          attention={o.stale_documents > 0}
        />
        <Tile
          k="Eval questions"
          v={o.accepted_questions}
          d={o.proposed_questions ? `${o.proposed_questions} proposed, awaiting review` : "none awaiting review"}
          href="/evals"
          attention={o.proposed_questions > 0}
        />
        <Tile
          k="Last end-to-end run"
          v={metrics ? pct(metrics.faithfulness) : "–"}
          d={o.last_eval_run ? `faithfulness · ${o.last_eval_run.id} · ${ago(o.last_eval_run.started_at)}` : "no runs yet"}
          href={o.last_eval_run ? `/evals/runs/${o.last_eval_run.id}` : "/evals"}
        />
        <Tile k="LLM cost, month to date" v={money(o.month_to_date_usd)} d="estimated" href="/costs" />
        <Tile k="Conversations, 7 days" v={o.conversations_7d} href="/conversations" />
      </div>

      {costs && (
        <div className="card">
          <div className="card-head">
            <h2>Daily LLM cost, last 30 days</h2>
            <Link to="/costs">Cost details</Link>
          </div>
          <CostChart daily={costs.daily} />
        </div>
      )}
    </>
  );
}
