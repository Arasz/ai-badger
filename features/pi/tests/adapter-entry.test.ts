/**
 * The hooks adapter's entry point, driven the way pi drives it: the default export registers
 * one `tool_call` handler, and the tests below call that handler for real — with a fake pi
 * and real `/bin/sh` gate commands — covering the branches the pure hook-bridge tests cannot
 * reach: gate loading per call, the once-only absence notice, the deny mapping, and away
 * mode's arming.
 */

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  createAgentSession,
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { fauxAssistantMessage, fauxProvider, fauxToolCall, type Context } from "@earendil-works/pi-ai";
import adapter from "../adjustments/adapter/index.ts";
import * as entry from "../adjustments/adapter/index.ts";
import type { BusDeps } from "../adjustments/adapter/index.ts";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;
type CommandSpec = { handler: (args: string[], ctx: unknown) => Promise<unknown> };

/** Install the default export against a fake pi and return the registered handler+commands. */
async function loadAdapterFor(_cwd?: string): Promise<{
  toolCall: Handler;
  toolResult: Handler;
  commands: Map<string, CommandSpec>;
}> {
  const on = new Map<string, Handler>();
  const commands = new Map<string, CommandSpec>();
  await adapter({
    on: (event: string, handler: Handler) => on.set(event, handler),
    registerCommand: (name: string, spec: CommandSpec) => commands.set(name, spec),
  } as never);
  return { toolCall: on.get("tool_call")!, toolResult: on.get("tool_result")!, commands };
}

/** Write a hooks.json holding one event's single matcher group. */
function writeHooks(dir: string, event: string, matcher: string, command: string): void {
  const hooksDir = join(dir, ".ai-badger", "hooks");
  mkdirSync(hooksDir, { recursive: true });
  writeFileSync(
    join(hooksDir, "hooks.json"),
    JSON.stringify({ hooks: { [event]: [{ matcher, hooks: [{ type: "command", command }] }] } }),
  );
}

/** True while `pid` is a live (not zombie) process. */
function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
  } catch {
    return false;
  }
  try {
    const stat = readFileSync(`/proc/${pid}/stat`, "utf-8");
    return stat.slice(stat.lastIndexOf(")") + 2, stat.lastIndexOf(")") + 3) !== "Z";
  } catch {
    return false;
  }
}

/** Poll until `pid` is gone or `ms` passes; the kill is asynchronous to the settle. */
async function goneWithin(pid: number, ms: number): Promise<boolean> {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    if (!alive(pid)) return true;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  return !alive(pid);
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

  test("a gate's systemMessage reaches the UI and the call proceeds", async () => {
    writeHooks(dir, "PreToolUse", "Bash", `printf '{"systemMessage":"dirty tree in another worktree"}'`);

    const { toolCall } = await loadAdapterFor(dir);
    const ctx = fakeCtx(dir);
    const result = await toolCall({ toolName: "bash", input: { command: "ls" } }, ctx);

    expect(result).toBeUndefined();
    expect(ctx.notices).toContain("dirty tree in another worktree");
  });

  test("a post hook's additionalContext is appended to the result; its systemMessage is a notice", async () => {
    writeHooks(
      dir,
      "PostToolUse",
      "Read",
      `printf '{"systemMessage":"look","hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"POST-X"}}'`,
    );

    const { toolResult } = await loadAdapterFor(dir);
    const ctx = fakeCtx(dir);
    const result = await toolResult(
      { toolName: "read", input: { path: "a" }, content: [{ type: "text", text: "body" }] },
      ctx,
    );

    expect(result).toEqual({
      content: [
        { type: "text", text: "body" },
        { type: "text", text: "POST-X" },
      ],
    });
    expect(ctx.notices).toContain("look");
  });

  test("a silent post hook leaves the result untouched", async () => {
    writeHooks(dir, "PostToolUse", "Read", "true");

    const { toolResult } = await loadAdapterFor(dir);
    const result = await toolResult(
      { toolName: "read", input: {}, content: [{ type: "text", text: "body" }] },
      fakeCtx(dir),
    );

    expect(result).toBeUndefined();
  });
});

describe("a hook spawn is bounded: the whole process group dies on timeout or abort", () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "aib-adapter-spawn-"));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  /** A compound command, as the shipped hooks.json entries are: the inner sh forks python
   * instead of exec'ing it, so python is a grandchild holding stdout/stderr open. */
  function sleeper(): { command: string; pidFile: string } {
    const pidFile = join(dir, "pid");
    const script = join(dir, "sleeper.py");
    writeFileSync(
      script,
      "import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(30)\n",
    );
    return { command: `sh -c 'python3 ${script} ${pidFile}; true'`, pidFile };
  }

  test("a timeout settles in under 2s and the grandchild is gone", async () => {
    const { command, pidFile } = sleeper();

    const started = Date.now();
    const outcome = await entry.runGate(command, {}, { cwd: dir, timeoutMs: 500 });
    const elapsed = Date.now() - started;

    expect(outcome.kind).toBe("error");
    expect(elapsed).toBeLessThan(2000);
    expect(await goneWithin(Number(readFileSync(pidFile, "utf-8")), 1000)).toBe(true);
  }, 10_000);

  test("an abort settles in under 2s and the grandchild is gone", async () => {
    const { command, pidFile } = sleeper();
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 500);

    const started = Date.now();
    const outcome = await entry.runGate(command, {}, { cwd: dir, signal: controller.signal });
    const elapsed = Date.now() - started;

    expect(outcome.kind).toBe("error");
    expect(elapsed).toBeLessThan(2000);
    expect(await goneWithin(Number(readFileSync(pidFile, "utf-8")), 1000)).toBe(true);
  }, 10_000);

  test("a ~256 KiB decision is read whole", async () => {
    const script = join(dir, "big.py");
    writeFileSync(
      script,
      "import json\nprint(json.dumps({'hookSpecificOutput': {'permissionDecision': 'deny', " +
        "'permissionDecisionReason': 'x' * 262144}}))\n",
    );

    const outcome = await entry.runGate(`python3 ${script}`, {}, { cwd: dir });

    expect(outcome).toEqual({ kind: "decision", decision: "deny", reason: "x".repeat(262144) });
  }, 10_000);

  test("output a descendant writes after the shell exits is still read: settle on close, not exit", async () => {
    // Bun reports `exit` only after a direct child's buffered output, so the plain 256 KiB
    // case cannot tell the two apart; a writer that outlives the shell can.
    const script = join(dir, "late.py");
    writeFileSync(
      script,
      "import json, time\ntime.sleep(0.3)\nprint(json.dumps({'hookSpecificOutput': " +
        "{'permissionDecision': 'deny', 'permissionDecisionReason': 'x' * 262144}}))\n",
    );

    const outcome = await entry.runGate(`python3 ${script} & exit 0`, {}, { cwd: dir });

    expect(outcome).toEqual({ kind: "decision", decision: "deny", reason: "x".repeat(262144) });
  }, 10_000);
});

describe("post-hook additionalContext is persisted, not a one-request copy", () => {
  const MARK = "POST-HOOK-CONTEXT-MARK";
  let root: string;

  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), "aib-adapter-post-"));
  });

  afterEach(() => {
    rmSync(root, { recursive: true, force: true });
  });

  /** One prompt through pi's real AgentSession, extension runner and agent loop; only the
   * LLM (pi-ai's faux provider) and the bus I/O are fakes. The model reads a file once, and
   * a Read post hook answers with additionalContext. */
  async function run(): Promise<{ nextRequest: number; persisted: number }> {
    const cwd = join(root, "project");
    const agentDir = join(root, "agent");
    mkdirSync(cwd, { recursive: true });
    mkdirSync(agentDir, { recursive: true });
    writeFileSync(join(cwd, "notes.txt"), "a file to read\n");
    writeHooks(
      cwd,
      "PostToolUse",
      "Read",
      `printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"${MARK}"}}'`,
    );

    const busDeps: BusDeps = {
      setInterval: () => ({}),
      clearInterval: () => {},
      probeBus: async () => ({ kind: "ok", fingerprint: { maxId: 0, count: 0, dev: 1, ino: 2 } }),
      deliver: async () => ({ kind: "empty" }),
    };

    const requests: Context[] = [];
    const faux = fauxProvider();
    faux.setResponses([
      (context: Context) => {
        requests.push(context);
        return fauxAssistantMessage(fauxToolCall("read", { path: "notes.txt" }), { stopReason: "toolUse" });
      },
      (context: Context) => {
        requests.push(context);
        return fauxAssistantMessage("done");
      },
    ]);

    const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false } });
    const resourceLoader = new DefaultResourceLoader({
      cwd,
      agentDir,
      settingsManager,
      extensionFactories: [(pi) => adapter(pi, busDeps)],
    });
    await resourceLoader.reload();
    const sessionManager = SessionManager.inMemory(cwd);
    const modelRuntime = await ModelRuntime.create({
      authPath: join(agentDir, "auth.json"),
      modelsPath: join(agentDir, "models.json"),
      allowModelNetwork: false,
      refreshOnCreate: false,
    });
    modelRuntime.registerNativeProvider(faux.provider);
    const { session } = await createAgentSession({
      cwd,
      agentDir,
      modelRuntime,
      model: faux.getModel(),
      tools: ["read"],
      resourceLoader,
      sessionManager,
      settingsManager,
    });
    await session.bindExtensions({});

    await session.prompt("hi");
    await session.agent.waitForIdle();
    session.dispose();

    const persisted = sessionManager.getEntries().filter(
      (item) =>
        item.type === "message" &&
        item.message.role === "toolResult" &&
        JSON.stringify(item).includes(MARK),
    );
    return {
      nextRequest: JSON.stringify(requests[1]?.messages ?? []).split(MARK).length - 1,
      persisted: persisted.length,
    };
  }

  test("the context is in the persisted tool result and on the next LLM request", async () => {
    expect(await run()).toEqual({ nextRequest: 1, persisted: 1 });
  }, 20_000);
});
