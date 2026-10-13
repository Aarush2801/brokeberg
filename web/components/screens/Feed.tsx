"use client";

import type { FeedResponse } from "@/lib/api";
import { Conf, FeedRow, Src, Topics, VerifyMark, shortTime, useTerminal } from "../primitives";

export default function Feed({ data }: { data: FeedResponse }) {
  const { run } = useTerminal();
  return (
    <>
      <div className="scr-head">FEED · what changed</div>
      <div className="scr-sub">
        last {data.window_days}d · ranked by salience (recency × sources × entity weight × verification × race
        proximity)
      </div>
      {data.rows.length === 0 && (
        <div className="empty">
          No events in the last {data.window_days} days — run the pipeline (make ingest-once → extract → cluster →
          graph), then FEED.
        </div>
      )}
      {data.rows.map((r) => (
        <FeedRow
          key={r.event_id}
          cmd={`EVT E${r.event_id}`}
          t={shortTime(r.event_time)}
          mv={<VerifyMark status={r.verification_status} />}
          meta={
            <>
              <Src url={r.source_url} span={r.span} tier={r.trust_tier} />
              {r.source_count > 1 && <span className="dim"> +{r.source_count - 1}</span>} · <Conf c={r.confidence} />
            </>
          }
        >
          {r.headline} &nbsp;<Topics topics={r.topics} />
        </FeedRow>
      ))}
      <hr className="rule dash" />
      <div className="label">
        click a headline → full event object · ✓ fact-checked/corroborated · · single source ·{" "}
        <span className="clk" role="button" tabIndex={0} onClick={() => run("HELP")} onKeyDown={(e) => e.key === "Enter" && run("HELP")}>
          HELP
        </span>{" "}
        for all commands
      </div>
    </>
  );
}
