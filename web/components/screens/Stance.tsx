"use client";

import type { StanceResponse } from "@/lib/api";
import { Conf, KV, Ref, Src, Table, Sparkline, posClass, words } from "../primitives";

export default function Stance({ d }: { d: StanceResponse }) {
  const ints = d.rows.flatMap((r) => (r.intensity === null ? [] : [r.intensity]));
  return (
    <>
      <div className="scr-head">
        STANCE · {d.entity.name} · {words(d.topic)}
      </div>
      <div className="scr-sub">position over time · span-grounded · {d.rows.length} statements</div>
      {d.rows.length === 0 ? (
        <div className="empty">
          No stance rows for {d.entity.name} on {words(d.topic)} — try{" "}
          <Ref cmd={`ENT ${d.entity.entity_id}`}>ENT {d.entity.name.toUpperCase()}</Ref> for topics with stances.
        </div>
      ) : (
        <>
          {ints.length > 0 && (
            <KV
              rows={[
                [
                  "Intensity trend",
                  <>
                    <Sparkline vals={ints} /> &nbsp;
                    <span className="dim">
                      {ints[0].toFixed(2)} → {ints[ints.length - 1].toFixed(2)}
                    </span>
                  </>,
                ],
              ]}
            />
          )}
          <hr className="rule" />
          <Table head={["Date", "Position", "int", "Grounding quote", "conf"]}>
            {d.rows.map((r) => (
              <tr key={`${r.event_id}-${r.span}`}>
                <td>
                  <Ref cmd={`EVT E${r.event_id}`}>{r.event_time.slice(0, 10)}</Ref>
                </td>
                <td className={posClass(r.stance)}>
                  {words(r.stance)}
                  {r.flip && <div className="flip">↺ flip</div>}
                </td>
                <td className="num">{r.intensity === null ? "—" : r.intensity.toFixed(2)}</td>
                <td>
                  &quot;{r.span}&quot; <Src url={r.source_url} span={r.span} tier={r.trust_tier} />
                </td>
                <td className="num">
                  <Conf c={r.confidence} />
                </td>
              </tr>
            ))}
          </Table>
        </>
      )}
      <hr className="rule dash" />
      <div className="label">every row traces to a stored source span — nothing synthesised</div>
    </>
  );
}
