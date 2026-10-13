// Terminal command parser: raw input -> one command. Pure, so it is unit-tested on its own.

export type Command =
  | { kind: "feed" }
  | { kind: "help" }
  | { kind: "event"; id: string }
  | { kind: "race"; id: string }
  | { kind: "entity"; ref: string }
  | { kind: "stance"; entity: string; topic: string }
  | { kind: "rsch"; question: string }
  | { kind: "error"; message: string };

const ALIASES: Record<string, Command["kind"]> = {
  FEED: "feed", F: "feed", CLEAR: "feed", CLS: "feed",
  HELP: "help", H: "help", "?": "help",
  EVT: "event", E: "event",
  RACE: "race", R: "race",
  ENT: "entity",
  STANCE: "stance", S: "stance",
  RSCH: "rsch", Q: "rsch",
};

export function parse(raw: string): Command | null {
  const text = raw.trim();
  if (!text) return null;
  const [head, ...rest] = text.split(/\s+/);
  const kind = ALIASES[head.toUpperCase()];
  const args = rest.map((a) => a.toUpperCase());

  switch (kind) {
    case "feed":
    case "help":
      return { kind };
    case "event":
      return args[0]
        ? { kind, id: args[0] }
        : { kind: "error", message: "EVT needs an event ID — e.g. EVT E42 (pick one from FEED)." };
    case "race":
      return args[0]
        ? { kind, id: args[0] }
        : { kind: "error", message: "RACE needs a race — e.g. RACE OH-SEN." };
    case "entity":
      return args.length
        ? { kind, ref: args.join(" ") }
        : { kind: "error", message: "ENT needs a name or ID — e.g. ENT MURKOWSKI." };
    case "stance":
      // The last word is the topic; everything before it names the entity.
      return args.length >= 2
        ? { kind, entity: args.slice(0, -1).join(" "), topic: args[args.length - 1] }
        : { kind: "error", message: "STANCE needs an entity and a topic — e.g. STANCE MURKOWSKI INFLATION." };
    case "rsch": {
      // Free text keeps its case: the question goes to retrieval as typed.
      const question = text.slice(head.length).trim();
      return question.length >= 3
        ? { kind, question }
        : { kind: "error", message: "RSCH needs a question — e.g. RSCH what did Murkowski say about CPI?" };
    }
    default:
      return { kind: "error", message: `Unknown command ${head.toUpperCase()} — type HELP for the list.` };
  }
}

/** How a command is echoed back in the hint line. */
export function echo(raw: string, cmd: Command): string {
  return cmd.kind === "rsch" ? `RSCH ${cmd.question}` : raw.trim().toUpperCase();
}
