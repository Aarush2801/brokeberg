"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ApiError, api,
  type EntityDossier, type EventObject, type FeedResponse, type Option, type QueryResponse,
  type RaceDossier, type StanceResponse, type TickerRow,
} from "@/lib/api";
import { echo, parse, type Command } from "@/lib/commands";
import { Ctx, Ref, host, srcTag, type Provenance } from "./primitives";
import Entity from "./screens/Entity";
import Event from "./screens/Event";
import Feed from "./screens/Feed";
import Help from "./screens/Help";
import Race from "./screens/Race";
import Rsch from "./screens/Rsch";
import Stance from "./screens/Stance";

type View =
  | { kind: "loading"; label: string }
  | { kind: "help" }
  | { kind: "feed"; data: FeedResponse }
  | { kind: "event"; data: EventObject }
  | { kind: "race"; data: RaceDossier }
  | { kind: "entity"; data: EntityDossier }
  | { kind: "stance"; data: StanceResponse }
  | { kind: "rsch"; data: QueryResponse }
  | { kind: "error"; message: string; options: Option[] };

const FEED_REFRESH_MS = 60_000;
const TICKER_REFRESH_MS = 5 * 60_000;

async function load(cmd: Exclude<Command, { kind: "help" | "error" }>): Promise<View> {
  switch (cmd.kind) {
    case "feed": return { kind: "feed", data: await api.feed() };
    case "event": return { kind: "event", data: await api.event(cmd.id) };
    case "race": return { kind: "race", data: await api.race(cmd.id) };
    case "entity": return { kind: "entity", data: await api.entity(cmd.ref) };
    case "stance": return { kind: "stance", data: await api.stance(cmd.entity, cmd.topic) };
    case "rsch": return { kind: "rsch", data: await api.query(cmd.question) };
  }
}

function Screen({ view }: { view: View }) {
  switch (view.kind) {
    case "loading": return <div className="loading">{view.label} </div>;
    case "help": return <Help />;
    case "feed": return <Feed data={view.data} />;
    case "event": return <Event e={view.data} />;
    case "race": return <Race r={view.data} />;
    case "entity": return <Entity d={view.data} />;
    case "stance": return <Stance d={view.data} />;
    case "rsch": return <Rsch d={view.data} />;
    case "error":
      return (
        <>
          <div className="scr-head err">⚠ {view.message}</div>
          {view.options.length > 0 && (
            <div className="tablewrap">
              <table>
                <tbody>
                  {view.options.map((o) => (
                    <tr key={o.command}>
                      <td>
                        <Ref cmd={o.command}>{o.label}</Ref>
                      </td>
                      <td className="dim">{o.command}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="label">
            Type <Ref cmd="HELP">HELP</Ref> for valid commands.
          </div>
        </>
      );
  }
}

function fmtTick(t: TickerRow): [string, string] {
  if (t.transform === "change") {
    const k = (v: number) => `${v >= 0 ? "+" : ""}${Math.round(v)}k`;
    return [k(t.value), t.delta === null ? "" : k(t.delta)];
  }
  const dp = t.transform === "yoy" ? 1 : 2;
  const d = t.delta === null ? "" : `${t.delta > 0 ? "+" : ""}${t.delta.toFixed(dp)}`;
  return [`${t.value.toFixed(dp)}%`, d];
}

export default function Terminal() {
  const [view, setView] = useState<View>({ kind: "loading", label: "fetching FEED…" });
  const [hint, setHint] = useState<ReactNode>(
    <>
      Type a command. <b>HELP</b> for the list · click any <span style={{ color: "var(--cyan)" }}>cyan</span> reference
      · <b>[SRC]</b> tags open provenance
    </>,
  );
  const [ticker, setTicker] = useState<TickerRow[] | null>(null);
  const [tickerErr, setTickerErr] = useState(false);
  const [live, setLive] = useState(true);
  const [prov, setProv] = useState<Provenance | null>(null);
  const [clock, setClock] = useState("—");
  const [value, setValue] = useState("");

  const seq = useRef(0);
  const screenRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const history = useRef<string[]>([]);
  const histIdx = useRef(-1);

  const run = useCallback((raw: string) => {
    const cmd = parse(raw);
    if (!cmd) return;
    const shown = echo(raw, cmd);
    const n = ++seq.current;
    setProv(null);
    screenRef.current?.scrollTo(0, 0);
    if (cmd.kind === "help") {
      setView({ kind: "help" });
      setHint(<><span className="dim">ran</span> <b>{shown}</b></>);
      return;
    }
    if (cmd.kind === "error") {
      setView({ kind: "error", message: cmd.message, options: [] });
      setHint(<span className="err">unrecognised — try HELP</span>);
      return;
    }
    setView({ kind: "loading", label: cmd.kind === "rsch" ? "retrieving records + grounding answer…" : `fetching ${shown}…` });
    setHint(<><span className="dim">running</span> <b>{shown}</b></>);
    load(cmd).then(
      (v) => {
        if (n !== seq.current) return; // a newer command superseded this one
        setLive(true);
        setView(v);
        setHint(<><span className="dim">ran</span> <b>{shown}</b></>);
      },
      (e: unknown) => {
        if (n !== seq.current) return;
        const err = e instanceof ApiError ? e : new ApiError(0, "Unexpected error — retry, or type HELP.");
        setLive(err.status !== 0 && err.status < 500);
        setView({ kind: "error", message: err.message, options: err.options });
        setHint(<><span className="dim">ran</span> <b>{shown}</b> <span className="err">· {err.status === 409 ? "ambiguous" : "failed"}</span></>);
      },
    );
  }, []);

  const showProv = useCallback((p: Provenance) => setProv(p), []);
  const ctx = useMemo(() => ({ run, showProv }), [run, showProv]);

  // Boot: FEED is pushed, not asked for.
  useEffect(() => {
    run("FEED");
    inputRef.current?.focus();
  }, [run]);

  // Push mode: while FEED is on screen, refresh it in place.
  useEffect(() => {
    if (view.kind !== "feed") return;
    const id = setInterval(() => {
      const n = seq.current;
      api.feed().then(
        (data) => {
          if (n === seq.current) {
            setLive(true);
            setView({ kind: "feed", data });
          }
        },
        () => setLive(false),
      );
    }, FEED_REFRESH_MS);
    return () => clearInterval(id);
  }, [view.kind]);

  useEffect(() => {
    const pull = () =>
      api.indicators().then(
        (rows) => {
          setTicker(rows);
          setTickerErr(false);
        },
        () => setTickerErr(true),
      );
    pull();
    const id = setInterval(pull, TICKER_REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const tick = () =>
      setClock(new Date().toLocaleTimeString("en-US", { hour12: false, timeZone: "America/New_York" }) + " ET");
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      if (value.trim()) {
        history.current.unshift(value);
        histIdx.current = -1;
      }
      run(value);
      setValue("");
    } else if (e.key === "ArrowUp") {
      if (histIdx.current < history.current.length - 1) {
        histIdx.current++;
        setValue(history.current[histIdx.current]);
        e.preventDefault();
      }
    } else if (e.key === "ArrowDown") {
      if (histIdx.current > 0) {
        histIdx.current--;
        setValue(history.current[histIdx.current]);
      } else {
        histIdx.current = -1;
        setValue("");
      }
      e.preventDefault();
    } else if (e.key === "Escape") {
      setProv(null);
    }
  }

  return (
    <Ctx.Provider value={ctx}>
      <div
        className="app"
        onClick={() => {
          if (window.getSelection()?.isCollapsed) inputRef.current?.focus();
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setProv(null);
        }}
      >
        <header>
          <span className="brand">
            BROKEBERG<span className="cur">▊</span>
          </span>
          <span className="scope">US FEDERAL · SENATE 2026</span>
          <span className="clock">
            {live ? (
              <span className="live">
                <span className="dot">●</span> LIVE
              </span>
            ) : (
              <span className="off">● OFFLINE</span>
            )}{" "}
            &nbsp;<span>{clock}</span>
          </span>
        </header>

        <div className="ticker">
          {tickerErr && !ticker && <div className="tick off">indicators unavailable — start the API with make api</div>}
          {ticker?.length === 0 && <div className="tick dim">no indicator data — run make ingest-once</div>}
          {ticker?.map((t) => {
            const [v, d] = fmtTick(t);
            const dir = t.delta === null || t.delta === 0 ? "" : t.delta > 0 ? "up" : "down";
            const open = () =>
              setProv({ url: t.source_url, span: t.span, note: `${t.label} · ${t.source.toUpperCase()} · as of ${t.asof}` });
            return (
              <div
                key={t.series_id}
                className="tick clk"
                role="button"
                tabIndex={0}
                title={`${t.series_id} · ${srcTag(t.source_url)} · as of ${t.asof}`}
                onClick={(e) => {
                  e.stopPropagation();
                  open();
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    open();
                  }
                }}
              >
                <span className="k">{t.label}</span> <span className="v">{v}</span>{" "}
                {dir === "up" ? <span className="up">▲</span> : dir === "down" ? <span className="down">▼</span> : <span className="dim">—</span>}
                {d && <span className={dir || "dim"}> {d}</span>}
              </div>
            );
          })}
        </div>

        <div className="screen" ref={screenRef} aria-live="polite">
          <Screen view={view} />
        </div>

        {prov && (
          <div className="prov" role="dialog" aria-label="Provenance" onClick={(e) => e.stopPropagation()}>
            <div className="row">
              <span className="src">[{srcTag(prov.url)}]</span>
              {prov.tier && <span className="dim">{prov.tier}</span>}
              {prov.note && <span className="dim">{prov.note}</span>}
              <button type="button" className="src x" onClick={() => setProv(null)}>
                close [esc]
              </button>
            </div>
            <a href={prov.url} target="_blank" rel="noreferrer">
              {prov.url}
            </a>
            <div className="quote">&quot;{prov.span}&quot;</div>
            <div className="dim">{host(prov.url)} · verbatim span as stored</div>
          </div>
        )}

        <div className="hint">{hint}</div>
        <div className="cmd">
          <span className="prompt">&gt;</span>
          {/* Autofill/password-manager extensions tag inputs (e.g. data-sharkid) before hydration. */}
          <input
            suppressHydrationWarning
            ref={inputRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Command"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            placeholder="e.g.  FEED · RACE OH-SEN · ENT MURKOWSKI · STANCE MURKOWSKI INFLATION · RSCH what changed on CPI?"
          />
        </div>
      </div>
    </Ctx.Provider>
  );
}
