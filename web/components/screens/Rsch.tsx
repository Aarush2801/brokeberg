"use client";

import type { QueryResponse } from "@/lib/api";
import { Conf, Ref, Section, Src, Table, host, srcTag, useTerminal } from "../primitives";

export default function Rsch({ d }: { d: QueryResponse }) {
  const { showProv } = useTerminal();
  const byN = new Map(d.sources.map((s) => [s.n, s]));
  return (
    <>
      <div className="scr-head">RSCH · {d.question}</div>
      <div className="scr-sub">
        grounded answer over {d.sources.length} retrieved records ·{" "}
        {d.refused ? "no answer" : <>conf <Conf c={d.confidence} /></>}
      </div>

      {d.refused ? (
        <div className="empty">{d.message}</div>
      ) : (
        d.claims.map((c, i) => (
          <div className="claim" key={i}>
            {c.text}{" "}
            {c.cited.map((n) => {
              const s = byN.get(n);
              return s ? (
                <button
                  key={n}
                  type="button"
                  className="src cite"
                  aria-label={`Citation ${n}: ${host(s.url)}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    showProv({ url: s.url, span: s.span, tier: s.trust_tier, note: `record ${n} · E${s.event_id}` });
                  }}
                >
                  [{n}]
                </button>
              ) : null;
            })}
          </div>
        ))
      )}

      {d.sources.length > 0 && (
        <Section label="Retrieved records">
          <Table head={["n", "Event", "Excerpt", "Src"]}>
            {d.sources.map((s) => (
              <tr key={s.n}>
                <td className="num">{s.n}</td>
                <td>
                  <Ref cmd={`EVT E${s.event_id}`}>E{s.event_id}</Ref>
                </td>
                <td>
                  {s.speaker && <span className="dim">{s.speaker}: </span>}
                  {s.span.length > 160 ? `${s.span.slice(0, 160)}…` : s.span}
                </td>
                <td>
                  <Src url={s.url} span={s.span} tier={s.trust_tier} note={`record ${s.n} · ${srcTag(s.url)}`} />
                </td>
              </tr>
            ))}
          </Table>
        </Section>
      )}

      {d.dropped_claims.length > 0 && (
        <>
          <hr className="rule" />
          <details>
            <summary>{d.dropped_claims.length} model claim(s) dropped by the grounding check</summary>
            {d.dropped_claims.map((c, i) => (
              <div className="claim dim" key={i}>
                <s>{c.text}</s> — {c.problems.join("; ")}
              </div>
            ))}
          </details>
        </>
      )}
      <hr className="rule dash" />
      <div className="label">
        answers come only from retrieved records · every claim cites one · confidence is computed from the cited
        sources, not by the model · co-occurrence, never causation
      </div>
    </>
  );
}
