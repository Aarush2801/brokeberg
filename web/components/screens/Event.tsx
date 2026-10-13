"use client";

import type { EventObject } from "@/lib/api";
import {
  Conf, FeedRow, Ref, Section, Src, Table, Topics, fullTime, posClass, rating, shortTime, words,
} from "../primitives";

interface NumericCheck {
  url: string;
  span: string;
  trust_tier: "T1" | "T2" | "T3" | "T4";
  series_id: string;
  period: string;
  claimed: number;
  yoy: boolean;
  references: Record<string, number>;
  result: string;
}

export default function Event({ e }: { e: EventObject }) {
  const numeric = (e.verification.numeric as NumericCheck[] | undefined) ?? [];
  const independent = e.verification.independent_sources as number | undefined;
  return (
    <>
      <div className="scr-head">
        E{e.id} &nbsp;{e.headline}
      </div>
      <div className="scr-sub">
        {fullTime(e.event_time)} · {words(e.event_type)} · <Topics topics={e.topics} /> · conf <Conf c={e.confidence} /> ·
        verified ({words(e.verification_status)}
        {independent !== undefined ? `, ${independent} independent source${independent === 1 ? "" : "s"}` : ""})
      </div>
      <div className="label">What happened</div>
      <div className="blurb">{e.what_happened ?? e.headline}</div>
      {e.why_it_matters && (
        <>
          <div className="label">Why it matters</div>
          <div className="blurb">{e.why_it_matters}</div>
        </>
      )}

      {e.political_reactions.length > 0 && (
        <Section label="Political reactions">
          <Table>
            {e.political_reactions.map((r) => (
              <tr key={`${r.entity_id}-${r.topic}`}>
                <td>
                  <Ref cmd={`ENT ${r.entity_id}`}>{r.name}</Ref>
                </td>
                <td className={posClass(r.stance)}>
                  {words(r.stance)}
                  {r.flip && (
                    <div className="flip">
                      ↺ reverses <Ref cmd={`EVT E${r.flip.prior_event_id}`}>{words(r.flip.prior_stance)}</Ref>
                    </div>
                  )}
                </td>
                <td>
                  <span className="topic">#{r.topic}</span> &quot;{r.span}&quot;{" "}
                  <Src url={r.source_url} span={r.span} tier={r.trust_tier} note={`${r.name} on ${r.topic}`} />
                </td>
                <td className="num">
                  <Conf c={r.confidence} />
                </td>
              </tr>
            ))}
          </Table>
        </Section>
      )}

      {numeric.length > 0 && (
        <Section label="Underlying data · numeric checks against stored indicators">
          <Table head={["Series", "Claimed", "Reference", "Result", "Src"]}>
            {numeric.map((c, i) => (
              <tr key={i}>
                <td>{c.series_id}{c.yoy ? " (YoY)" : ""} <span className="dim">{c.period}</span></td>
                <td>{c.claimed}</td>
                <td>
                  {Object.entries(c.references).map(([k, v]) => `${k.toUpperCase()} ${v}`).join(" · ") || "—"}
                </td>
                <td className={c.result === "match" ? "up" : c.result === "mismatch" ? "down" : "dim"}>
                  {words(c.result)}
                </td>
                <td>
                  <Src url={c.url} span={c.span} tier={c.trust_tier} />
                </td>
              </tr>
            ))}
          </Table>
        </Section>
      )}

      <Section label="Affected elections">
        {e.affected_elections.length === 0 ? (
          <div className="empty">Not linked to a seeded race — RACE &lt;code&gt; shows each race&apos;s linked events.</div>
        ) : (
          <Table head={["Race", "Rating", "Rationale", "conf"]}>
            {e.affected_elections.map((x) => (
              <tr key={x.race_id}>
                <td>
                  <Ref cmd={`RACE ${x.race_id}`}>{x.race_id}</Ref>
                </td>
                <td>{rating(x.rating)}</td>
                <td>{x.rationale}</td>
                <td className="num">
                  <Conf c={x.confidence} />
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Section>

      {e.entities.length > 0 && (
        <Section label="Entities">
          <div className="blurb">
            {e.entities.map((x, i) => (
              <span key={x.entity_id}>
                {i ? " · " : ""}
                <Ref cmd={`ENT ${x.entity_id}`}>{x.name}</Ref> <span className="dim">({x.roles.join(", ")})</span>
              </span>
            ))}
          </div>
        </Section>
      )}

      {e.related_events.length > 0 && (
        <Section label="Related events">
          {e.related_events.map((r) => (
            <FeedRow
              key={r.event_id}
              cmd={`EVT E${r.event_id}`}
              t={shortTime(r.event_time)}
              meta={
                <>
                  {r.direction} · {words(r.relation).toLowerCase()} · <Conf c={r.confidence} />
                </>
              }
            >
              {r.headline}
            </FeedRow>
          ))}
        </Section>
      )}

      <hr className="rule dash" />
      <div className="label">
        Sources:{" "}
        {e.sources.map((s, i) => (
          <span key={i}>
            <Src url={s.url} span={s.span} tier={s.trust_tier} />{" "}
          </span>
        ))}
      </div>
    </>
  );
}
