/**
 * The memory-first gate in pi: the search runs, the model receives the memory result, and
 * the user sees nothing.
 *
 * The gate is the framework's own hook (ai-badger's `memory_first_gate_hook.py`), speaking
 * the Claude envelope. Its quiet decision carries the memory result as `additionalContext`
 * and no permission decision at all — the search is not blocked and no payload is rendered.
 * The adapter's job is to hand that context to the model without occupying the user
 * channel: a user-role turn would make the model read the memory result as something the
 * user said, and would cost an extra LLM call. The context rides the tool result instead
 * (ADR-0045).
 */

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import adapter from "../adjustments/adapter/index.ts";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;

interface SentMessage {
  customType: string;
  content: string;
  display?: boolean;
}

interface Block {
  type: string;
  text: string;
}

/** Install the default export against a fake pi that records the messages it sends. */
async function loadAdapter(): Promise<{
  toolCall: Handler;
  toolResult: Handler;
  sent: SentMessage[];
}> {
  const on = new Map<string, Handler>();
  const sent: SentMessage[] = [];
  await adapter({
    on: (event: string, handler: Handler) => on.set(event, handler),
    registerCommand: () => undefined,
    sendMessage: (message: SentMessage) => {
      sent.push(message);
    },
  } as never);
  return { toolCall: on.get("tool_call")!, toolResult: on.get("tool_result")!, sent };
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
  function writeGate(output: unknown, post?: unknown): void {
    const hooksDir = join(dir, ".ai-badger", "hooks");
    mkdirSync(hooksDir, { recursive: true });
    const command = (payload: unknown) => `printf '%s' '${JSON.stringify(payload)}'`;
    writeFileSync(
      join(hooksDir, "hooks.json"),
      JSON.stringify({
        hooks: {
          PreToolUse: [
            {
              matcher: "Bash",
              hooks: [{ type: "command", command: command(output) }],
            },
          ],
          ...(post
            ? {
                PostToolUse: [
                  {
                    matcher: "Bash",
                    hooks: [{ type: "command", command: command(post) }],
                  },
                ],
              }
            : {}),
        },
      }),
    );
  }

  const MEMORY = "## Memory context\n- hit: docs/merge.md";

  test("the memory result rides the tool result, and no user turn carries it", async () => {
    writeGate({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        additionalContext: MEMORY,
      },
    });

    const { toolCall, toolResult, sent } = await loadAdapter();
    const call = await toolCall(
      { toolName: "bash", toolCallId: "call-1", input: { command: "grep -n foo f.py" } },
      fakeCtx(dir),
    );

    // The call is not blocked, and nothing was sent to the user channel.
    expect(call).toBeUndefined();
    expect(sent).toHaveLength(0);

    const result = (await toolResult(
      {
        toolName: "bash",
        toolCallId: "call-1",
        input: { command: "grep -n foo f.py" },
        content: [{ type: "text", text: "f.py:1:foo" }],
      },
      fakeCtx(dir),
    )) as { content: Block[] } | undefined;

    const text = (result?.content ?? []).map((block) => block.text).join("\n");
    expect(text).toContain("hit: docs/merge.md");
    expect(text).toContain("f.py:1:foo");
    expect(sent).toHaveLength(0);
  });

  test("a denied call carries no memory result into a later tool result", async () => {
    writeGate(
      {
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: "Memory-first: search memory for \"foo\" first, then re-run this search.",
          // A gate may block a call and still hand the model context: the context must
          // not outlive the call it belonged to.
          additionalContext: MEMORY,
        },
      },
      {
        hookSpecificOutput: {
          hookEventName: "PostToolUse",
          additionalContext: "## Post note",
        },
      },
    );

    const { toolCall, toolResult, sent } = await loadAdapter();
    const result = await toolCall(
      { toolName: "bash", toolCallId: "call-1", input: { command: "grep -n foo f.py" } },
      fakeCtx(dir),
    );

    expect(result).toEqual({
      block: true,
      reason: "Memory-first: search memory for \"foo\" first, then re-run this search.",
    });
    expect(sent).toHaveLength(0);

    // The same call id: a host that retries a blocked call reuses it. Nothing the blocked
    // call carried may reach a result.
    const later = (await toolResult(
      {
        toolName: "bash",
        toolCallId: "call-1",
        input: { command: "ls" },
        content: [{ type: "text", text: "f.py" }],
      },
      fakeCtx(dir),
    )) as { content: Block[] } | undefined;

    const text = (later?.content ?? []).map((block) => block.text).join("\n");
    expect(text).not.toContain("Memory context");
    expect(text).toContain("f.py");
  });
});
