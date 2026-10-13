"use client";

// The mockup's render helpers (src, confTag, topics, posClass, sparkline, feed row) as components.

import { createContext, useContext, type KeyboardEvent, type ReactNode } from "react";
import type { TrustTier } from "@/lib/api";

export interface Provenance {
  url: string;
  span: string;
  tier?: TrustTier;
  note?: string;
}

interface TerminalCtx {
  run: (command: string) => void;
  showProv: (p: Provenance) => void;
}

export const Ctx = createContext<TerminalCtx>({ run: () => {}, showProv: () => {} });
export const useTerminal = () => useContext(Ctx);

// Source tag from the URL host: the short labels the mockup used.
const HOST_TAGS: [RegExp, string][] = [
  [/(^|\.)congress\.gov$/, "CNG"],
  [/(^|\.)stlouisfed\.org$/, "FRED"],
  [/(^|\.)bls\.gov$/, "BLS"],
  [/(^|\.)fec\.gov$/, "FEC"],
  [/(^|\.)(x|twitter)\.com$/, "X"],
  [/(^|\.)senate\.gov$/, "PR"],
  [/(^|\.)house\.gov$/, "PR"],
  [/(^|\.)whitehouse\.gov$/, "WH"],
  [/(^|\.)cookpolitical\.com$/, "COOK"],
  [/(^|\.)centerforpolitics\.org$/, "SABATO"],
  [/(^|\.)insideelections\.com$/, "INSIDE"],
  [/(^|\.)nytimes\.com$/, "NYT"],
];

export function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function srcTag(url: string): string {
  const h = host(url);
  const hit = HOST_TAGS.find(([re]) => re.test(h));
  return hit ? hit[1] : h.split(".").slice(-2, -1)[0]?.toUpperCase() || "SRC";
}

/** `[TAG]` — opens the provenance pane (URL + verbatim span + trust tier). */
export function Src({ url, span, tier, note }: Provenance) {
  const { showProv } = useTerminal();
  const tag = srcTag(url);
  return (
    <button
      type="button"
      className="src"
      title={`${tier ? tier + " · " : ""}${host(url)} — show source`}
      aria-label={`Source ${tag}: ${host(url)}`}
      onClick={(e) => {
        e.stopPropagation();
        showProv({ url, span, tier, note });
      }}
    >
      [{tag}]
    </button>
  );
}

export function Conf({ c }: { c: number }) {
  const cls = c >= 0.85 ? "hi" : c < 0.7 ? "lo" : "";
  return <span className={`conf ${cls}`}>{c.toFixed(2)}</span>;
}

export function Topics({ topics }: { topics: string[] }) {
  return (
    <>
      {topics.map((t, i) => (
        <span key={t}>
          {i ? " " : ""}
          <span className="topic">#{t}</span>
        </span>
      ))}
    </>
  );
}

export function posClass(p: string): string {
  if (/support/.test(p)) return "pos-s";
  if (/oppose/.test(p)) return "pos-o";
  return "pos-n";
}

export const words = (s: string) => s.replace(/_/g, " ");

export function Sparkline({ vals }: { vals: number[] }) {
  const bars = "▁▂▃▄▅▆▇█";
  const mn = Math.min(...vals);
  const mx = Math.max(...vals);
  const s = vals.map((v) => bars[mx === mn ? 3 : Math.round(((v - mn) / (mx - mn)) * 7)]).join("");
  return <span className="spark">{s}</span>;
}

/** A cyan cross-reference that runs a terminal command. */
export function Ref({ cmd, children }: { cmd: string; children: ReactNode }) {
  const { run } = useTerminal();
  return (
    <a
      className="ref"
      href="#"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        run(cmd);
      }}
    >
      {children}
    </a>
  );
}

function activate(e: KeyboardEvent, fn: () => void) {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fn();
  }
}

/** A clickable, keyboard-focusable row: time · marker · headline · meta. */
export function FeedRow({
  cmd, t, mv, meta, children,
}: { cmd: string; t: ReactNode; mv?: ReactNode; meta?: ReactNode; children: ReactNode }) {
  const { run } = useTerminal();
  const go = () => run(cmd);
  return (
    <div
      className="feed-row"
      role="button"
      tabIndex={0}
      onClick={(e) => {
        e.stopPropagation();
        go();
      }}
      onKeyDown={(e) => activate(e, go)}
    >
      <span className="t">{t}</span>
      {mv !== undefined && <span className="mv">{mv}</span>}
      <span className="hd">{children}</span>
      {meta !== undefined && <span className="meta">{meta}</span>}
    </div>
  );
}

/** Verification status as the feed's marker column. */
export function VerifyMark({ status }: { status: string }) {
  const [glyph, cls] =
    status === "fact_checked" ? ["✓", "up"]
    : status === "corroborated" ? ["✓", "conf"]
    : status === "contradicted" ? ["✗", "down"]
    : status === "single_source" ? ["·", "dim"]
    : ["?", "dim"];
  return <span className={cls} title={words(status)}>{glyph}</span>;
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <div className="kv">
      {rows.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <div className="k">{k}</div>
          <div className="v">{v}</div>
        </div>
      ))}
    </div>
  );
}

export function Section({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <>
      <hr className="rule" />
      <div className="label">{label}</div>
      {children}
    </>
  );
}

export function Table({ head, children }: { head?: ReactNode[]; children: ReactNode }) {
  return (
    <div className="tablewrap">
      <table>
        <tbody>
          {head && (
            <tr>
              {head.map((h, i) => (
                <th key={i} className={typeof h === "string" && /^(conf|int|n)$/.test(h) ? "num" : undefined}>
                  {h}
                </th>
              ))}
            </tr>
          )}
          {children}
        </tbody>
      </table>
    </div>
  );
}

// --- formatting ------------------------------------------------------------------------------

const ET = "America/New_York";

function etDay(d: Date): string {
  return d.toLocaleDateString("en-CA", { timeZone: ET });
}

/** The mockup's time column: HH:MM today, "Yd" yesterday, MM-DD before that (Eastern). */
export function shortTime(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const today = etDay(now);
  const yesterday = etDay(new Date(now.getTime() - 86_400_000));
  const day = etDay(d);
  if (day === today) {
    return d.toLocaleTimeString("en-US", { timeZone: ET, hour12: false, hour: "2-digit", minute: "2-digit" });
  }
  if (day === yesterday) return "Yd";
  return day.slice(5);
}

export function fullTime(iso: string): string {
  const d = new Date(iso);
  return `${etDay(d)} ${d.toLocaleTimeString("en-US", { timeZone: ET, hour12: false, hour: "2-digit", minute: "2-digit" })} ET`;
}

export function rating(r: string | null): string {
  if (!r) return "unrated";
  if (r === "tossup") return "Tossup";
  const [lean, party] = r.split("_");
  return `${lean[0].toUpperCase()}${lean.slice(1)} ${party.toUpperCase()}`;
}

export function money(v: unknown): string {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}
