"use client";

import { Ref } from "../primitives";

const CMDS: [string, string, string][] = [
  ["FEED", "live 'what changed' — the default screen (push, no query)", "FEED"],
  ["EVT <id>", "full event object — the E-number from FEED", "FEED"],
  ["RACE <code>", "race dossier — e.g. RACE OH-SEN", "RACE OH-SEN"],
  ["ENT <name | id>", "entity dossier — e.g. ENT MURKOWSKI", "ENT MURKOWSKI"],
  ["STANCE <ent> <topic>", "position timeline — e.g. STANCE MURKOWSKI INFLATION", "STANCE MURKOWSKI INFLATION"],
  ["RSCH <question>", "grounded answer over retrieved records, with citations + confidence", "RSCH what changed on inflation?"],
  ["HELP", "this screen", "HELP"],
];

export default function Help() {
  return (
    <>
      <div className="scr-head">HELP · command reference</div>
      <div className="scr-sub">each command is a query over one shared graph · ↑/↓ recalls history</div>
      <div className="tablewrap">
        <table>
          <tbody>
            {CMDS.map(([c, d, ex]) => (
              <tr key={c}>
                <td style={{ color: "var(--amber)" }}>{c}</td>
                <td>
                  {d} <Ref cmd={ex}>run</Ref>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <hr className="rule dash" />
      <div className="label">
        push mode runs on its own (FEED). pull mode = you ask; RSCH answers only from retrieved records, every claim
        cites one, and claims that don&apos;t ground are dropped. click any [SRC] tag for its URL + verbatim span.
      </div>
    </>
  );
}
