import { describe, expect, it } from "vitest";
import { echo, parse } from "./commands";

describe("parse", () => {
  it("ignores blank input", () => {
    expect(parse("   ")).toBeNull();
  });

  it("maps aliases, case-insensitively", () => {
    for (const raw of ["FEED", "f", "cls", "clear"]) expect(parse(raw)).toEqual({ kind: "feed" });
    for (const raw of ["HELP", "h", "?"]) expect(parse(raw)).toEqual({ kind: "help" });
  });

  it("parses event and race references", () => {
    expect(parse("evt e42")).toEqual({ kind: "event", id: "E42" });
    expect(parse("E 42")).toEqual({ kind: "event", id: "42" });
    expect(parse("race az-sen")).toEqual({ kind: "race", id: "AZ-SEN" });
    expect(parse("R OH-SEN-2026")).toEqual({ kind: "race", id: "OH-SEN-2026" });
  });

  it("joins multi-word entity names", () => {
    expect(parse("ENT lisa murkowski")).toEqual({ kind: "entity", ref: "LISA MURKOWSKI" });
    expect(parse("ENT bioguide:M001153")).toEqual({ kind: "entity", ref: "BIOGUIDE:M001153" });
  });

  it("takes the last STANCE word as the topic", () => {
    expect(parse("STANCE murkowski tariffs")).toEqual({
      kind: "stance", entity: "MURKOWSKI", topic: "TARIFFS",
    });
    expect(parse("S lisa murkowski inflation")).toEqual({
      kind: "stance", entity: "LISA MURKOWSKI", topic: "INFLATION",
    });
  });

  it("keeps RSCH free text as typed", () => {
    expect(parse("rsch What did Murkowski say about CPI?")).toEqual({
      kind: "rsch", question: "What did Murkowski say about CPI?",
    });
    expect(parse("Q  tariffs  and   steel ")).toEqual({ kind: "rsch", question: "tariffs  and   steel" });
  });

  it("returns a direction when arguments are missing", () => {
    for (const raw of ["EVT", "RACE", "ENT", "STANCE MURKOWSKI", "RSCH"]) {
      const cmd = parse(raw);
      expect(cmd?.kind).toBe("error");
      expect(cmd && "message" in cmd && cmd.message).toMatch(/ — e\.g\. /);
    }
  });

  it("rejects unknown commands", () => {
    expect(parse("FOO bar")).toEqual({
      kind: "error", message: "Unknown command FOO — type HELP for the list.",
    });
  });
});

describe("echo", () => {
  it("upper-cases commands but not research questions", () => {
    expect(echo(" evt e42 ", parse("evt e42")!)).toBe("EVT E42");
    expect(echo("rsch why CPI?", parse("rsch why CPI?")!)).toBe("RSCH why CPI?");
  });
});
