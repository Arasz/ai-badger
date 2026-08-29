/**
 * ai-badger hooks adapter for pi: runs the project's Claude-shaped PreToolUse gates before
 * every tool call and maps their decision back onto pi's `{ block, reason }` contract.
 *
 * Installed user-scope at `~/.pi/agent/extensions/ai-badger/index.ts`, never project-local:
 * `.pi/extensions/` is trust-gated, and pi's settings docs state that `-p`, `--mode json` and
 * `--mode rpc` ignore project resources without a saved trust decision — a project-local gate
 * would gate nothing in exactly the headless runs it is most needed for.
 */

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  commandsForTool,
  createAwayState,
  parseHookStdout,
  preToolUseCommands,
  resolve,
  toClaudePayload,
  type GateOutcome,
  type HookCommand,
} from "./hook-bridge.ts";

const GATE_TIMEOUT_MS = 5000;
const HOOKS_CONFIG = [".ai-badger", "hooks", "hooks.json"];

/** Projects already reported as having no hook config; absence is announced once, not per call. */
const absenceReported = new Set<string>();

type Gates = { commands: HookCommand[] } | { absent: string } | { broken: string };

function loadGates(cwd: string): Gates {
  const path = join(cwd, ...HOOKS_CONFIG);
  let raw: string;
  try {
    raw = readFileSync(path, "utf-8");
  } catch {
    return { absent: `${path} does not exist` };
  }
  try {
    return { commands: preToolUseCommands(JSON.parse(raw)) };
  } catch (error) {
    return { broken: `${path} is not valid JSON (${String(error)})` };
  }
}

/** Run one gate command, converting every failure mode into a reportable error outcome. */
function runGate(
  command: string,
  payload: unknown,
  ctx: { cwd: string; signal: AbortSignal | undefined },
): Promise<GateOutcome> {
  return new Promise((settle) => {
    let child;
    try {
      child = spawn("/bin/sh", ["-c", command], {
        cwd: ctx.cwd,
        env: { ...process.env, CLAUDE_PROJECT_DIR: ctx.cwd },
        signal: ctx.signal,
        timeout: GATE_TIMEOUT_MS,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (error) {
      settle({ kind: "error", reason: `${command} could not start (${String(error)})` });
      return;
    }

    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr?.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", (error) => {
      settle({ kind: "error", reason: `${command} failed (${String(error)})` });
    });
    child.on("close", (code, signal) => {
      if (signal) {
        settle({ kind: "error", reason: `${command} was killed after ${GATE_TIMEOUT_MS}ms` });
        return;
      }
      if (code !== 0) {
        settle({
          kind: "error",
          reason: `${command} exited ${code}: ${stderr.trim().slice(-400) || "(no stderr)"}`,
        });
        return;
      }
      const decision = parseHookStdout(stdout);
      if (decision === null) {
        settle({
          kind: "error",
          reason: `${command} printed output that is not a hook decision: ${stdout.trim().slice(0, 200)}`,
        });
        return;
      }
      settle({ kind: "decision", decision: decision.decision, reason: decision.reason });
    });

    // A gate that exits or is killed before reading stdin makes this write fail with EPIPE.
    // That is the gate's failure, already reported by the close handler, not a crash for pi.
    child.stdin?.on("error", () => {});
    try {
      child.stdin?.end(JSON.stringify(payload));
    } catch {
      // same case, thrown synchronously
    }
  });
}

/** Every gate outcome for one tool call, including "there are no gates here". */
async function gateOutcomes(
  event: { toolName: string; input: Record<string, unknown> },
  ctx: ExtensionContext,
): Promise<GateOutcome[]> {
  const gates = loadGates(ctx.cwd);
  if ("broken" in gates) return [{ kind: "error", reason: gates.broken }];
  if ("absent" in gates) {
    if (absenceReported.has(ctx.cwd)) return [];
    absenceReported.add(ctx.cwd);
    return [{ kind: "absent", reason: gates.absent }];
  }

  const payload = toClaudePayload(event, {
    cwd: ctx.cwd,
    sessionId: process.env.PI_SESSION_ID ?? "",
  });
  const commands = commandsForTool(gates.commands, payload.tool_name);
  return Promise.all(
    commands.map((command) => runGate(command, payload, { cwd: ctx.cwd, signal: ctx.signal })),
  );
}

export default async function (pi: ExtensionAPI) {
  // Away mode lives here because pi has no API letting one extension answer another's dialog:
  // the confirm this adapter raises can only be pre-empted by this adapter.
  const away = createAwayState(process.env);

  if (typeof pi?.on !== "function") {
    console.error(
      "ai-badger: pi.on is not a function — this pi build's extension API has moved; the hook gate is not installed.",
    );
    return;
  }

  const apiComplete = typeof pi.registerCommand === "function";
  let apiWarned = false;

  pi.on("tool_call", async (event, ctx) => {
    if (!apiWarned && !apiComplete) {
      apiWarned = true;
      ctx.ui.notify(
        "ai-badger: pi.registerCommand is missing — this pi build's extension API has moved; commands are unavailable.",
        "warning",
      );
    }

    const outcomes = await gateOutcomes(
      { toolName: event.toolName, input: event.input as Record<string, unknown> },
      ctx,
    );
    const resolution = resolve(outcomes, { armed: away.armed(), hasUI: ctx.hasUI });
    for (const notice of resolution.notices) ctx.ui.notify(notice, "warning");

    if (resolution.action === "block") {
      return { block: true, reason: resolution.reason ?? "blocked by an ai-badger hook gate" };
    }
    if (resolution.action === "confirm") {
      const approved = await ctx.ui.confirm(
        "ai-badger hook gate",
        resolution.reason ?? "Allow this tool call?",
      );
      if (!approved) return { block: true, reason: resolution.reason ?? "declined" };
    }
    return undefined;
  });

  if (!apiComplete) return;
  pi.registerCommand("away", {
    description: "Toggle ai-badger away mode: auto-approve hook gates that ask (never a deny)",
    handler: async (_args, ctx) => {
      const armed = away.toggle();
      ctx.ui.notify(
        armed
          ? "ai-badger away mode ON — an explicit 'ask' is auto-approved and notified; denials and gate errors are unaffected."
          : "ai-badger away mode OFF — an 'ask' prompts again.",
        "info",
      );
    },
  });
}
