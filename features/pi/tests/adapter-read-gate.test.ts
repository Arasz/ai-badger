/**
 * The read gate as the adapter wires it: pi's `read` tool reaches the framework's
 * memory-first hook before the file is read, and only a bank answer stops the read.
 * These tests drive the real `tool_call` handler with a fake gate script on disk.
 */

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import adapter from "../adjustments/adapter/index.ts";
import { READ_GATE_ENV } from "../adjustments/adapter/read-gate.ts";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;

/** Install the default export against a fake pi and return the registered handlers. */
async function loadAdapter(): Promise<{ toolCall: Handler }> {
  const on = new Map<string, Handler>();
  await adapter({
    on: (event: string, handler: Handler) => on.set(event, handler),
    registerCommand: () => {},
  } as never);
  return { toolCall: on.get("tool_call")! };
}

/** A pi extension context with a notify sink and no UI — the headless shape. */
function fakeCtx(cwd: string): Record<string, unknown> & { notices: string[] } {
  const notices: string[] = [];
  return {
    cwd,
    hasUI: false,
    signal: undefined,
    ui: { notify: (m: string) => notices.push(m), confirm: async () => false },
    notices,
  };
}

/** Install a fake framework gate script that records the payload it received. */
function writeGate(dir: string, hits: string | null): string {
  const scriptDir = join(dir, ".ai-badger", "skills", "ai-raccoon-memory", "scripts");
  mkdirSync(scriptDir, { recursive: true });
  const payloadFile = join(dir, "payload.json");
  const script = join(scriptDir, "memory_first_gate_hook.py");
  writeFileSync(
    script,
    [
      "import json, os, sys",
      "payload = json.load(sys.stdin)",
      "open(os.environ['READ_GATE_PAYLOAD'], 'w').write(json.dumps(payload))",
      "reason = json.dumps({'searchResult': {'mem_search_result_output': " + JSON.stringify(hits) + "}, 'rawGrepInput': []})",
      "print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': reason}}))",
    ].join("\n"),
  );
  return payloadFile;
}

describe("the adapter's read gate", () => {
  let dir: string;
  let payloadFile: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "aib-read-gate-"));
    payloadFile = join(dir, "payload.json");
    process.env.READ_GATE_PAYLOAD = payloadFile;
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
    delete process.env.READ_GATE_PAYLOAD;
    delete process.env[READ_GATE_ENV];
  });

  test("a bank answer stops the read and hands the model the memory result", async () => {
    writeGate(dir, "- memories: /repo/src/app.ts is already indexed");

    const { toolCall } = await loadAdapter();
    const result = await toolCall({ toolName: "read", input: { path: "src/app.ts" } }, fakeCtx(dir));

    expect(result).toEqual({
      block: true,
      reason: expect.stringContaining("src/app.ts"),
    });
    const reason = (result as { reason: string }).reason;
    expect(reason).toContain("is already indexed");
    expect(reason).toContain("re-issue the same read");
  });

  test("the gate is asked about the path the read names, in the framework's search shape", async () => {
    writeGate(dir, "- memories: a hit");

    const { toolCall } = await loadAdapter();
    await toolCall({ toolName: "read", input: { path: "src/app.ts" } }, fakeCtx(dir));

    const payload = JSON.parse(readFileSync(payloadFile, "utf-8"));
    expect(payload.tool_name).toBe("search_files");
    expect(payload.tool_input).toEqual({ pattern: "src/app.ts" });
    expect(payload.hook_event_name).toBe("PreToolUse");
  });

  test("a bank with nothing to offer lets the read through", async () => {
    writeGate(dir, "(no hits)");

    const { toolCall } = await loadAdapter();
    const result = await toolCall({ toolName: "read", input: { path: "src/app.ts" } }, fakeCtx(dir));

    expect(result).toBeUndefined();
  });

  test("a project without the gate script lets the read through", async () => {
    const { toolCall } = await loadAdapter();
    const result = await toolCall({ toolName: "read", input: { path: "src/app.ts" } }, fakeCtx(dir));

    expect(result).toBeUndefined();
  });

  test("the switch turns the gate off", async () => {
    writeGate(dir, "- memories: a hit");
    process.env[READ_GATE_ENV] = "0";

    const { toolCall } = await loadAdapter();
    const result = await toolCall({ toolName: "read", input: { path: "src/app.ts" } }, fakeCtx(dir));

    expect(result).toBeUndefined();
  });

  test("a gate that fails lets the read through", async () => {
    const scriptDir = join(dir, ".ai-badger", "skills", "ai-raccoon-memory", "scripts");
    mkdirSync(scriptDir, { recursive: true });
    writeFileSync(join(scriptDir, "memory_first_gate_hook.py"), "import sys\nsys.exit(3)\n");

    const { toolCall } = await loadAdapter();
    const result = await toolCall({ toolName: "read", input: { path: "src/app.ts" } }, fakeCtx(dir));

    expect(result).toBeUndefined();
  });

  test("a read without a path is not gated", async () => {
    writeGate(dir, "- memories: a hit");

    const { toolCall } = await loadAdapter();
    const result = await toolCall({ toolName: "read", input: {} }, fakeCtx(dir));

    expect(result).toBeUndefined();
    expect(() => readFileSync(payloadFile, "utf-8")).toThrow();
  });
});
