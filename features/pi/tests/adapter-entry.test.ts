/**
 * The hooks adapter's entry point, driven the way pi drives it: the default export registers
 * one `tool_call` handler, and the tests below call that handler for real — with a fake pi
 * and real `/bin/sh` gate commands — covering the branches the pure hook-bridge tests cannot
 * reach: gate loading per call, the once-only absence notice, the deny mapping, and away
 * mode's arming.
 */

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import adapter from "../adjustments/adapter/index.ts";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;
type CommandSpec = { handler: (args: string[], ctx: unknown) => Promise<unknown> };

/** Install the default export against a fake pi and return the registered handler+commands. */
async function loadAdapterFor(_cwd?: string): Promise<{
  toolCall: Handler;
  commands: Map<string, CommandSpec>;
}> {
  const on = new Map<string, Handler>();
  const commands = new Map<string, CommandSpec>();
  await adapter({
    on: (event: string, handler: Handler) => on.set(event, handler),
    registerCommand: (name: string, spec: CommandSpec) => commands.set(name, spec),
  } as never);
  return { toolCall: on.get("tool_call")!, commands };
}

/** A pi extension context with a notify sink and no UI — the headless shape. */
function fakeCtx(cwd: string): Record<string, unknown> & { notices: string[]; autoApproved?: boolean } {
  const notices: string[] = [];
  return {
    cwd,
    hasUI: false,
    signal: undefined,
    ui: { notify: (m: string) => notices.push(m), confirm: async () => false },
    notices,
  };
}

describe("adapter entry point", () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "aib-adapter-"));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
    delete process.env.AI_BADGER_PI_AWAY;
  });

  test("registers exactly one tool_call handler and the away command", async () => {
    const { toolCall, commands } = await loadAdapterFor(dir);

    expect(typeof toolCall).toBe("function");
    expect([...commands.keys()]).toEqual(["away"]);
  });

  test("a denying gate blocks the call with the gate's reason", async () => {
    const hooksDir = join(dir, ".ai-badger", "hooks");
    mkdirSync(hooksDir, { recursive: true });
    writeFileSync(
      join(hooksDir, "hooks.json"),
      JSON.stringify({
        hooks: {
          PreToolUse: [
            {
              matcher: "Bash",
              hooks: [{
                type: "command",
                command:
                  `printf '{"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"guarded"}}'`,
              }],
            },
          ],
        },
      }),
    );

    const { toolCall } = await loadAdapterFor(dir);
    const ctx = fakeCtx(dir);
    const result = await toolCall({ toolName: "bash", input: { command: "cat /etc/hosts" } }, ctx);

    expect(result).toEqual({ block: true, reason: "guarded" });
  });

  test("a gate command that exits non-zero allows with a 'gate failed' notice", async () => {
    const hooksDir = join(dir, ".ai-badger", "hooks");
    mkdirSync(hooksDir, { recursive: true });
    writeFileSync(join(hooksDir, "hooks.json"), JSON.stringify({
      hooks: { PreToolUse: [{ matcher: "Bash", hooks: [{ command: "exit 3" }] }] },
    }));

    const { toolCall } = await loadAdapterFor(dir);
    const ctx = fakeCtx(dir);
    const result = await toolCall({ toolName: "bash", input: { command: "ls" } }, ctx);

    expect(result).toBeUndefined();
    expect(ctx.notices.some((n: string) => n.includes("hook gate failed"))).toBe(true);
  });

  test("absence of hooks.json is announced once, then stays silent", async () => {
    const { toolCall } = await loadAdapterFor(dir);
    const first = fakeCtx(dir);
    const second = fakeCtx(dir);

    await toolCall({ toolName: "bash", input: {} }, first);
    await toolCall({ toolName: "bash", input: {} }, second);

    expect(first.notices.filter((n: string) => n.includes("no hook gates"))).toHaveLength(1);
    expect(second.notices.filter((n: string) => n.includes("no hook gates"))).toHaveLength(0);
  });

  test("away mode auto-approves an ask and says so in the trail", async () => {
    process.env.AI_BADGER_PI_AWAY = "1";
    const hooksDir = join(dir, ".ai-badger", "hooks");
    mkdirSync(hooksDir, { recursive: true });
    writeFileSync(join(hooksDir, "hooks.json"), JSON.stringify({
      hooks: {
        PreToolUse: [
          {
            matcher: "Bash",
            hooks: [
              {
                type: "command",
                command:
                  `printf '{"hookSpecificOutput":{"permissionDecision":"ask","permissionDecisionReason":"confirm me"}}'`,
              },
            ],
          },
        ],
      },
    }));

    const { toolCall } = await loadAdapterFor(dir);
    const ctx = fakeCtx(dir);
    const result = await toolCall({ toolName: "bash", input: { command: "rm -rf /" } }, ctx);

    expect(result).toBeUndefined();
    expect(ctx.notices.some((n: string) => n.includes("away mode auto-approved"))).toBe(true);
  });

  test("the away command toggles arming within the session", async () => {
    const { commands } = await loadAdapterFor(dir);
    const away = commands.get("away") as CommandSpec;
    const ctx = fakeCtx(dir);

    await away.handler([], ctx);
    expect(ctx.notices.join(" ")).toContain("away mode ON");

    await away.handler([], ctx);
    expect(ctx.notices.join(" ")).toContain("away mode OFF");
  });
});
