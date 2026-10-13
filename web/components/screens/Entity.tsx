"use client";

import type { EntityDossier } from "@/lib/api";
import { Conf, FeedRow, Ref, Section, Src, Table, posClass, shortTime, words } from "../primitives";

export default function Entity({ d }: { d: EntityDossier }) {
  const id = d.entity.entity_id;
  return (
    <>
      <div className="scr-head">{d.entity.name}</div>
      <div className="scr-sub">
        {d.entity.entity_type} · <span className="dim">{d.entity.canonical_id}</span>
      </div>

      <div className="label">
        Stance summary &nbsp;<span className="dim">(latest per topic · click a topic → timeline)</span>
      </div>
      {d.stances.length === 0 ? (
        <div className="empty">No grounded stances yet — positions appear once this entity&apos;s statements are extracted.</div>
      ) : (
        <Table head={["Topic", "Position", "Grounding quote", "conf"]}>
          {d.stances.map((s) => (
            <tr key={s.topic}>
              <td>
                <Ref cmd={`STANCE ${id} ${s.topic.toUpperCase()}`}>{s.topic}</Ref>
              </td>
              <td className={posClass(s.stance)}>
                {words(s.stance)}
                {s.flip && <div className="flip">↺ was {words(s.flip.prior_stance)}</div>}
              </td>
              <td>
                &quot;{s.span}&quot; <Src url={s.source_url} span={s.span} tier={s.trust_tier} />
              </td>
              <td className="num">
                <Conf c={s.confidence} />
              </td>
            </tr>
          ))}
        </Table>
      )}

      <Section label="Recent events">
        {d.recent_events.length === 0 && <div className="empty">No event objects mention this entity yet.</div>}
        {d.recent_events.map((e) => (
          <FeedRow
            key={e.event_id}
            cmd={`EVT E${e.event_id}`}
            t={shortTime(e.event_time)}
            meta={<Src url={e.source_url} span={e.span} tier={e.trust_tier} />}
          >
            {e.headline} &nbsp;<span className="dim">({e.roles.join(", ")})</span>
          </FeedRow>
        ))}
      </Section>

      {d.relationships.length > 0 && (
        <Section label="Relationships">
          <Table head={["", "Relation", "Entity", "Events", "Src", "conf"]}>
            {d.relationships.map((r) => (
              <tr key={`${r.direction}-${r.relation}-${r.entity_id}`}>
                <td className="dim">{r.direction === "out" ? "→" : "←"}</td>
                <td>{words(r.relation).toLowerCase()}</td>
                <td>
                  <Ref cmd={`ENT ${r.entity_id}`}>{r.name}</Ref>
                </td>
                <td>
                  <Ref cmd={`EVT E${r.event_id}`}>E{r.event_id}</Ref>
                  {r.edge_count > 1 && <span className="dim"> +{r.edge_count - 1}</span>}
                </td>
                <td>
                  <Src url={r.source_url} span={r.span} note={r.rationale ?? undefined} />
                </td>
                <td className="num">
                  <Conf c={r.confidence} />
                </td>
              </tr>
            ))}
          </Table>
        </Section>
      )}
    </>
  );
}
