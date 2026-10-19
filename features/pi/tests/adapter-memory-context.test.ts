/**
 * The memory-first gate in pi: the search runs, the model receives the memory result, and
 * the user sees nothing.
 *
 * The gate is the framework's own hook (ai-badger's `memory_first_gate_hook.py`), speaking
 * the Claude envelope. Its quiet decision carries the memory result as `additionalContext`
 * and no permission decision at all — the search is not blocked and no payload is rendered.
 * The adapter's job is to hand that context to the model (a custom message pi does not
 * render) and to leave the call alone.
 */

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import adapter from "../adjustments/adapter/index.ts";
import { MEMORY_CONTEXT_CUSTOM_TYPE } from "../adjustments/adapter/hook-bridge.ts";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;

interface SentMessage {
  customType: string;
  content: string;
  display?: boolean;
}

/** Install the default export against a fake pi that records the messages it sends. */
async function loadAdapter(): Promise<{ toolCall: Handler; sent: SentMessage[] }> {
  const on = new Map<string, Handler>();
  const sent: SentMessage[] = [];
  await adapter({
    on: (event: string, handler: Handler) => on.set(event, handler),
    registerCommand: () => undefined,
    sendMessage: (message: SentMessage) => {
      sent.push(message);
    },
  } as never);
  return { toolCall: on.get("tool_call")!, sent };
}

/** A pi extension context with a notify sink and no UI — the headless shape. */
function fakeCtx(cwd: string): { cwd: string; hasUI: boolean; ui: { notify: (m: string) => void } } {
  return { cwd, hasUI: false, ui: { notify: () => undefined } };
}

describe("the memory-first gate in pi", () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "aib-memory-gate-"));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  /** Write a hooks.json whose PreToolUse gate prints the given JSON on stdout. */
  function writeGate(output: unknown): void {
    const hooksDir = join(dir, ".ai-badger", "hooks");
    mkdirSync(hooksDir, { recursive: true });
    writeFileSync(
      join(hooksDir, "hooks.json"),
      JSON.stringify({
        hooks: {
          PreToolUse: [
            {
              matcher: "Bash",
              hooks: [{ type: "command", command: `printf '%s' '${JSON.stringify(output)}'` }],
            },
          ],
        },
      }),
    );
  }

  test("the search is not blocked and the memory result reaches the model unrendered", async () => {
    writeGate({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        additionalContext: "## Memory context\n- hit: docs/merge.md",
      },
    });

    const { toolCall, sent } = await loadAdapter();
    const result = await toolCall({ toolName: "bash", input: { command: "grep -n foo f.py" } }, fakeCtx(dir));

    expect(result).toBeUndefined();
    expect(sent).toHaveLength(1);
    expect(sent[0].customType).toBe(MEMORY_CONTEXT_CUSTOM_TYPE);
    expect(sent[0].content).toContain("hit: docs/merge.md");
    expect(sent[0].display).toBe(false);
  });

  test("a denying gate still blocks the call with its reason", async () => {
    writeGate({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Memory-first: search memory for \"foo\" first, then re-run this search.",
      },
    });

    const { toolCall, sent } = await loadAdapter();
    const result = await toolCall({ toolName: "bash", input: { command: "grep -n foo f.py" } }, fakeCtx(dir));

    expect(result).toEqual({
      block: true,
      reason: "Memory-first: search memory for \"foo\" first, then re-run this search.",
    });
    expect(sent).toHaveLength(0);
  });
});
