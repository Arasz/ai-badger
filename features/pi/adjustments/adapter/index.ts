/**
 * ai-badger hooks adapter for pi: runs the project's Claude-shaped PreToolUse gates before
 * every tool call and maps their decision back onto pi's `{ block, reason }` contract, and
 * runs the PostToolUse entries (marker recorders, memory telemetry) after every tool result
 * — advisory only, never touching the result. Both arms read the project's
 * `.ai-badger/hooks/hooks.json` at event time; both carry the same session id, because the
 * consulted marker a post arm records is looked up by the pre arm.
 *
 * Installed user-scope at `~/.pi/agent/extensions/ai-badger/index.ts`, never project-local:
 * `.pi/extensions/` is trust-gated, and pi's settings docs state that `-p`, `--mode json` and
 * `--mode rpc` ignore project resources without a saved trust decision — a project-local gate
 * would gate nothing in exactly the headless runs it is most needed for.
 */

import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  commandsForTool,
  createAwayState,
  createDeliveryRouter,
  parseDeliveryStdout,
  parseHookStdout,
  postCommandsForTool,
  postToolUseCommands,
  preToolUseCommands,
  resolve,
  resolvePost,
  resolveSessionId,
  toClaudeDeliveryPayload,
  toClaudePayload,
  toClaudePostPayload,
  type ClaudeDeliveryPayload,
  type DeliveryOutcome,
  type GateOutcome,
  type HookCommand,
  type PostOutcome,
} from "./hook-bridge.ts";

const GATE_TIMEOUT_MS = 5000;
const HOOKS_CONFIG = [".ai-badger", "hooks", "hooks.json"];

/** Projects already reported as having no hook config; absence is announced once, not per call. */
const absenceReported = new Set<string>();

type Gates = { pre: HookCommand[]; post: HookCommand[] } | { absent: string } | { broken: string };

function loadGates(cwd: string): Gates {
  const path = join(cwd, ...HOOKS_CONFIG);
  let raw: string;
  try {
    raw = readFileSync(path, "utf-8");
  } catch {
    return { absent: `${path} does not exist` };
  }
  try {
    const parsed = JSON.parse(raw);
    return { pre: preToolUseCommands(parsed), post: postToolUseCommands(parsed) };
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
    sessionId: resolveSessionId(ctx, process.env),
  });
  const broken: string[] = [];
  const commands = commandsForTool(gates.pre, payload.tool_name, (reason) => broken.push(reason));
  const outcomes = await Promise.all(
    commands.map((command) => runGate(command, payload, { cwd: ctx.cwd, signal: ctx.signal })),
  );
  // A matcher that does not compile skips its command; that is reported like a gate error
  // rather than vanishing, so a typo'd shipped matcher cannot silently gate nothing.
  return [...broken.map((reason): GateOutcome => ({ kind: "error", reason })), ...outcomes];
}

/** Run one PostToolUse command, converting every failure mode into a reportable outcome.
 * Mirrors runGate's spawn discipline but never parses a decision: post hooks are advisory
 * side effects (marker recording, telemetry), and their stdout is theirs alone. */
function runPostHook(
  command: string,
  payload: unknown,
  ctx: { cwd: string; signal: AbortSignal | undefined },
): Promise<PostOutcome> {
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

    let stderr = "";
    child.stdout?.resume(); // drain: post hooks may print; nobody parses it
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
      settle({ kind: "ok" });
    });

    child.stdin?.on("error", () => {});
    try {
      child.stdin?.end(JSON.stringify(payload));
    } catch {
      // same case, thrown synchronously
    }
  });
}

/** Every post-hook outcome for one tool result. A missing hooks config stays silent here —
 * the pre arm already reports absence once per cwd, and post hooks are advisory. */
async function postHookOutcomes(
  event: { toolName: string; input?: Record<string, unknown>; content?: unknown },
  ctx: ExtensionContext,
): Promise<PostOutcome[]> {
  const gates = loadGates(ctx.cwd);
  if ("broken" in gates) return [{ kind: "error", reason: gates.broken }];
  if ("absent" in gates) return [];

  const payload = toClaudePostPayload(event, {
    cwd: ctx.cwd,
    sessionId: resolveSessionId(ctx, process.env),
  });
  const broken: string[] = [];
  const commands = postCommandsForTool(gates.post, payload.tool_name, (reason) =>
    broken.push(reason),
  );
  const outcomes = await Promise.all(
    commands.map((command) => runPostHook(command, payload, { cwd: ctx.cwd, signal: ctx.signal })),
  );
  return [...broken.map((reason): PostOutcome => ({ kind: "error", reason })), ...outcomes];
}

/** Run one delivery-script firing for the message bus. Mirrors runGate's spawn
discipline (env-redirected CLAUDE_PROJECT_DIR, timeout, stdin JSON) but never parses a
decision — the response is the mail document the bridge parses. A project without the
script is an UNWIRED project (Rule 7 scenario 2): silent no-op, never a notice, never
a spawn — the adapter is installed user-globally and most projects have no bus. */
async function runDelivery(
  payload: ClaudeDeliveryPayload,
  ctx: { cwd: string; signal: AbortSignal | undefined },
): Promise<DeliveryOutcome> {
  const script = join(ctx.cwd, ".ai-badger", "hooks", "message_delivery_hook.py");
  if (!existsSync(script)) return { kind: "empty" };
  return new Promise((settle) => {
    let child;
    try {
      child = spawn("python3", [script], {
        cwd: ctx.cwd,
        env: { ...process.env, CLAUDE_PROJECT_DIR: ctx.cwd },
        signal: ctx.signal,
        timeout: GATE_TIMEOUT_MS,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (error) {
      settle({ kind: "error", reason: `${script} could not start (${String(error)})` });
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
      settle({ kind: "error", reason: `${script} failed (${String(error)})` });
    });
    child.on("close", (code, signal) => {
      if (signal) {
        settle({ kind: "error", reason: `${script} was killed after ${GATE_TIMEOUT_MS}ms` });
        return;
      }
      if (code !== 0) {
        settle({
          kind: "error",
          reason: `${script} exited ${code}: ${stderr.trim().slice(-400) || "(no stderr)"}`,
        });
        return;
      }
      settle(parseDeliveryStdout(stdout));
    });

    child.stdin?.on("error", () => {});
    try {
      child.stdin?.end(JSON.stringify(payload));
    } catch {
      // same case, thrown synchronously
    }
  });
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

  // Skills contribution (plan §1 M4, decision D2): UNGATED. pi honors
  // source-verified skillPaths in all modes (agent-session.js:1920-1941) and
  // derives the event from the session cwd (runner.js:935-947), so the handler
  // reads event.cwd and never the extension context — no ctx.cwd, no
  // isProjectTrusted(): the effective trust decision is installing this adapter
  // user-globally (ADR-0023's recorded asymmetry, calibrated by the pre-existing
  // hooks-shell-command channel, ADR-0022). Absent-safe: a project without
  // .ai-badger/skills contributes no paths and never throws.
  pi.on("resources_discover", (event) => {
    const skillsDir = join(event.cwd, ".ai-badger", "skills");
    if (!existsSync(skillsDir)) return { skillPaths: [] };
    return { skillPaths: [skillsDir] };
  });

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

  pi.on("tool_result", async (event, ctx) => {
    const outcomes = await postHookOutcomes(
      {
        toolName: event.toolName,
        input: (event.input ?? {}) as Record<string, unknown>,
        content: (event as { content?: unknown }).content,
      },
      ctx,
    );
    for (const notice of resolvePost(outcomes).notices) ctx.ui.notify(notice, "warning");
    return undefined; // advisory: the tool result is never modified
  });

  // Message-bus delivery (plan aib-user-db-message-bus §3 P6; start-spawn deferred per
  // D4/P4): the same Claude-shaped delivery script Claude and Copilot run, translated
  // through the bridge's router. There is no session_start delivery — a session that
  // never turns consumes nothing. before_agent_start injects through the result-message
  // seam; the per-turn context event appends mail that arrived between LLM calls;
  // session_shutdown is cursor cleanup.
  const deliveryCtx = (ctx: ExtensionContext) => ({
    cwd: ctx.cwd,
    sessionId: resolveSessionId(ctx, process.env),
  });
  const router = createDeliveryRouter((payload) => runDelivery(payload, { cwd: payload.cwd, signal: undefined }));

  pi.on("before_agent_start", async (_event, ctx) => {
    const { injection, notices } = await router.beforeAgentStart(deliveryCtx(ctx));
    for (const notice of notices) ctx.ui.notify(notice, "warning");
    return injection; // undefined = inject nothing this turn
  });

  pi.on("context", async (event, ctx) => {
    const { injection, notices } = await router.context(deliveryCtx(ctx));
    for (const notice of notices) ctx.ui.notify(notice, "warning");
    if (!injection) return undefined; // no mail between tasks: the array passes through unmodified
    return { messages: [...event.messages, injection.message] };
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    const { notices } = await router.sessionShutdown(deliveryCtx(ctx));
    for (const notice of notices) {
      try {
        ctx.ui.notify(notice, "warning");
      } catch {
        // the UI may already be tearing down; the cleanup itself has fired either way
      }
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
