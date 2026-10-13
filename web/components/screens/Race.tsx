"use client";

import type { RaceDossier } from "@/lib/api";
import { Conf, FeedRow, KV, Ref, Section, Src, Table, Topics, money, rating, shortTime } from "../primitives";

export default function Race({ r }: { r: RaceDossier }) {
  const [state, office] = r.race_id.split("-");
  const daysOut = Math.ceil((new Date(r.election_day).getTime() - Date.now()) / 86_400_000);
  const [current, ...older] = r.rating_history;
  const topics = [...new Set(r.linked_events.flatMap((e) => e.matched_topics))];
  return (
    <>
      <div className="scr-head">
        {r.race_id} &nbsp;{state} · U.S. {office === "SEN" ? "Senate" : r.office} · {r.cycle}
      </div>
      <div className="scr-sub">
        RACE dossier · election day {r.election_day}
        {daysOut >= 0 ? ` · ${daysOut}d out` : ""}
        {topics.length > 0 && (
          <>
            {" "}· <Topics topics={topics} />
          </>
        )}
      </div>
      <KV
        rows={[
          [
            "Rating",
            current ? (
              <>
                {rating(r.rating)} &nbsp;
                <span className="dim">
                  ({[current, ...older].map((h) => `${h.rater} ${rating(h.rating)} [${h.asof}]`).join(" · ")})
                </span>{" "}
                <Src url={current.source_url} span={`${current.rater}: ${rating(current.rating)} as of ${current.asof}`} />
              </>
            ) : (
              <span className="dim">{rating(r.rating)} — no sourced rating yet</span>
            ),
          ],
          [
            "Poll avg",
            r.poll_average ? (
              <>
                {Number(r.poll_average.value) > 0 ? "+" : ""}
                {r.poll_average.value} &nbsp;
                <span className="dim">
                  {Object.entries(r.poll_average.meta).map(([k, v]) => `${k} ${String(v)}`).join(" · ")} ·{" "}
                  {r.poll_average.asof}
                </span>{" "}
                <Src url={r.poll_average.source_url} span={`poll average ${r.poll_average.value} as of ${r.poll_average.asof}`} />
              </>
            ) : (
              <span className="dim">no poll average ingested</span>
            ),
          ],
          [
            "Incumbent",
            r.incumbent ? <Ref cmd={`ENT ${r.incumbent.entity_id}`}>{r.incumbent.name}</Ref> : <span className="dim">open seat / unknown</span>,
          ],
        ]}
      />

      <Section label={<>Candidates {r.finance_asof && <span className="dim">· FEC as of {r.finance_asof}</span>}</>}>
        {r.candidates.length === 0 ? (
          <div className="empty">No FEC candidates on file — run make ingest-once to pull filings.</div>
        ) : (
          <Table head={["Name", "Party", "Cash on hand", "Raised", "Src"]}>
            {r.candidates.map((c) => {
              const f = c.finance ?? {};
              const name = c.name ?? c.fec_candidate_id;
              return (
                <tr key={c.fec_candidate_id}>
                  <td>
                    {c.entity_id ? <Ref cmd={`ENT ${c.entity_id}`}>{name}</Ref> : name}
                    {f.incumbent_challenge === "I" && <span className="dim"> (inc)</span>}
                  </td>
                  <td>{String(f.party ?? "—")}</td>
                  <td className="num">{money(f.cash_on_hand_end_period)}</td>
                  <td className="num">{money(f.receipts)}</td>
                  <td>
                    {r.finance_source_url ? (
                      <Src
                        url={r.finance_source_url}
                        span={`${name}: receipts ${money(f.receipts)}, cash on hand ${money(f.cash_on_hand_end_period)}`}
                        note={c.fec_candidate_id}
                      />
                    ) : (
                      <span className="dim">{c.fec_candidate_id}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </Table>
        )}
      </Section>

      <Section label="Recent linked events">
        {r.linked_events.length === 0 && (
          <div className="empty">No events linked to {r.race_id} yet — FEED shows everything ingested.</div>
        )}
        {r.linked_events.map((e) => (
          <FeedRow
            key={e.event_id}
            cmd={`EVT E${e.event_id}`}
            t={shortTime(e.event_time)}
            meta={
              <>
                <Src url={e.source_url} span={e.span} tier={e.trust_tier} note={e.rationale} /> · <Conf c={e.confidence} />
              </>
            }
          >
            {e.headline} &nbsp;<span className="dim">{e.rationale}</span>
          </FeedRow>
        ))}
      </Section>
    </>
  );
}
