/**
 * The memory-first read gate: pi's `read` tool is redirected to the ai-raccoon bank before
 * the file is read, the same way the framework's memory-first gate redirects a text search.
 * The bank answers first; the raw file is the fallback the model asks for by re-issuing the
 * read. These tests pin the pure translation — the payload the framework gate reads, and the
 * decision that payload produces.
 */

import { describe, expect, test } from "bun:test";
import {
  parseReadGateStdout,
  readGatePayload,
  readGateReason,
  readGateScript,
  readPattern,
  READ_GATE_ENV,
  readGateEnabled,
} from "../adjustments/adapter/read-gate.ts";

/** The framework gate's deny envelope, with the memory result JSON as its reason. */
function deny(hits: string | null): string {
  const payload = JSON.stringify({
    searchResult: { mem_search_result_output: hits },
    rawGrepInput: [],
  });
  return JSON.stringify({
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: payload,
    },
  });
}

describe("the read gate's payload", () => {
  test("the gate script is the framework's memory-first hook inside the project", () => {
    expect(readGateScript("/repo")).toBe(
      "/repo/.ai-badger/skills/ai-raccoon-memory/scripts/memory_first_gate_hook.py",
    );
  });

  test("the pattern is the file path the read names", () => {
    expect(readPattern({ path: "src/app.ts" })).toBe("src/app.ts");
    expect(readPattern({ path: "" })).toBeNull();
    expect(readPattern({ path: "   " })).toBeNull();
    expect(readPattern({})).toBeNull();
    expect(readPattern(undefined)).toBeNull();
  });

  test("the payload reads as a search for that path, in the framework's own shape", () => {
    const payload = readGatePayload("/repo/src/app.ts", { cwd: "/repo", sessionId: "s1" });

    expect(payload).toEqual({
      hook_event_name: "PreToolUse",
      session_id: "s1",
      cwd: "/repo",
      tool_name: "search_files",
      tool_input: { pattern: "/repo/src/app.ts" },
    });
  });
});

describe("the read gate's decision", () => {
  test("a bank answer blocks the read and hands the model the memory result", () => {
    const outcome = parseReadGateStdout(deny("- memories: the file is already indexed"), "/repo/a.ts");

    expect(outcome.kind).toBe("block");
    if (outcome.kind !== "block") return;
    expect(outcome.reason).toContain("/repo/a.ts");
    expect(outcome.reason).toContain("the file is already indexed");
    expect(outcome.reason).toContain("re-issue the same read");
  });

  test("no hits lets the read through — the bank had nothing to offer", () => {
    expect(parseReadGateStdout(deny("(no hits)"), "/repo/a.ts").kind).toBe("allow");
    expect(parseReadGateStdout(deny(""), "/repo/a.ts").kind).toBe("allow");
  });

  test("a bank that could not search lets the read through", () => {
    expect(parseReadGateStdout(deny(null), "/repo/a.ts").kind).toBe("allow");
  });

  test("silence, an allow decision and unparseable output all let the read through", () => {
    expect(parseReadGateStdout("", "/repo/a.ts").kind).toBe("allow");
    expect(parseReadGateStdout(JSON.stringify({ hookSpecificOutput: { permissionDecision: "allow" } }), "/repo/a.ts").kind).toBe("allow");
    expect(parseReadGateStdout("not json at all", "/repo/a.ts").kind).toBe("allow");
  });

  test("a deny whose reason is not the memory payload lets the read through", () => {
    const stdout = JSON.stringify({
      hookSpecificOutput: { permissionDecision: "deny", permissionDecisionReason: "plain text" },
    });

    expect(parseReadGateStdout(stdout, "/repo/a.ts").kind).toBe("allow");
  });
});

describe("the read gate's reason", () => {
  test("it names the file, carries the payload verbatim, and says how to get the raw file", () => {
    const payload = JSON.stringify({ searchResult: { mem_search_result_output: "hits" } });
    const reason = readGateReason("/repo/a.ts", payload);

    expect(reason).toContain("/repo/a.ts");
    expect(reason).toContain(payload);
    expect(reason).toContain("skip the read");
    expect(reason).toContain("re-issue the same read");
  });
});

describe("the read gate's switch", () => {
  test("on unless the environment says exactly 0", () => {
    expect(readGateEnabled({})).toBe(true);
    expect(readGateEnabled({ [READ_GATE_ENV]: "0" })).toBe(false);
    expect(readGateEnabled({ [READ_GATE_ENV]: "1" })).toBe(true);
    expect(readGateEnabled({ [READ_GATE_ENV]: "false" })).toBe(true);
  });
});
