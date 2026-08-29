import { describe, expect, test } from "bun:test";
import {
  awayFromEnv,
  claudeToolInput,
  claudeToolName,
  commandsForTool,
  parseHookStdout,
  preToolUseCommands,
  resolve,
  toClaudePayload,
  type GateOutcome,
} from "../adjustments/adapter/hook-bridge.ts";

describe("hooks.json is the list of gates, not a hardcoded copy of it", () => {
  const hooksJson = {
    hooks: {
      PreToolUse: [
        { matcher: "Agent", hooks: [{ type: "command", command: "python3 dispatch.py" }] },
        {
          matcher: "Grep|Glob|Bash",
          hooks: [{ type: "command", command: "python3 memory_gate.py" }],
        },
        { hooks: [{ type: "command", command: "python3 always.py" }] },
      ],
      PostToolUse: [{ hooks: [{ type: "command", command: "python3 post.py" }] }],
    },
  };

  test("only PreToolUse entries are collected", () => {
    const commands = preToolUseCommands(hooksJson);
    expect(commands.map((c) => c.command)).toEqual([
      "python3 dispatch.py",
      "python3 memory_gate.py",
      "python3 always.py",
    ]);
  });

  test("a missing or malformed hooks.json yields no gates rather than throwing", () => {
    expect(preToolUseCommands(null)).toEqual([]);
    expect(preToolUseCommands({ hooks: { PreToolUse: "nope" } })).toEqual([]);
  });

  test("a matcher selects by full tool name, and a matcher-less entry always runs", () => {
    const commands = preToolUseCommands(hooksJson);
    expect(commandsForTool(commands, "Bash")).toEqual([
      "python3 memory_gate.py",
      "python3 always.py",
    ]);
    expect(commandsForTool(commands, "Read")).toEqual(["python3 always.py"]);
    expect(commandsForTool(commands, "Agent")).toEqual([
      "python3 dispatch.py",
      "python3 always.py",
    ]);
  });

  test("a matcher is anchored: Bash does not match BashOutput", () => {
    const commands = preToolUseCommands(hooksJson);
    expect(commandsForTool(commands, "BashOutput")).toEqual(["python3 always.py"]);
  });

  test("an unparseable matcher regex is skipped, not crashed on, and the skip is reported", () => {
    const commands = preToolUseCommands({
      hooks: { PreToolUse: [{ matcher: "([", hooks: [{ command: "python3 broken.py" }] }] },
    });
    const broken: string[] = [];
    expect(commandsForTool(commands, "Bash", (reason) => broken.push(reason))).toEqual([]);
    expect(broken).toHaveLength(1);
    expect(broken[0]).toContain("([");
  });
});

describe("pi tool events translate into the Claude shape ai-badger's hooks parse", () => {
  test("tool names map onto the names the shipped matchers use", () => {
    expect(claudeToolName("bash")).toBe("Bash");
    expect(claudeToolName("powershell")).toBe("Bash");
    expect(claudeToolName("read")).toBe("Read");
    expect(claudeToolName("edit")).toBe("MultiEdit");
    expect(claudeToolName("write")).toBe("Write");
    expect(claudeToolName("grep")).toBe("Grep");
    expect(claudeToolName("find")).toBe("Glob");
    expect(claudeToolName("ls")).toBe("LS");
  });

  test("a custom tool keeps its own name", () => {
    expect(claudeToolName("my_mcp_tool")).toBe("my_mcp_tool");
  });

  test("bash input keeps the `command` key the guards read", () => {
    expect(claudeToolInput("bash", { command: "git status", timeout: 5 })).toEqual({
      command: "git status",
    });
  });

  test("path-shaped inputs become `file_path`, which is what the git and generated-file guards read", () => {
    expect(claudeToolInput("read", { path: "/a/b.py", offset: 2 })).toEqual({
      file_path: "/a/b.py",
      offset: 2,
    });
    expect(claudeToolInput("write", { path: "/a/b.py", content: "x" })).toEqual({
      file_path: "/a/b.py",
      content: "x",
    });
  });

  test("pi's edit becomes MultiEdit's edits[] with old_string/new_string", () => {
    expect(
      claudeToolInput("edit", {
        path: "/a/b.py",
        edits: [
          { oldText: "one", newText: "two" },
          { oldText: "three", newText: "four" },
        ],
      }),
    ).toEqual({
      file_path: "/a/b.py",
      edits: [
        { old_string: "one", new_string: "two" },
        { old_string: "three", new_string: "four" },
      ],
    });
  });

  test("grep and find keep `pattern` and pass their search root as `path`", () => {
    expect(claudeToolInput("grep", { pattern: "TODO", path: "src" })).toEqual({
      pattern: "TODO",
      path: "src",
    });
    expect(claudeToolInput("find", { pattern: "*.ts" })).toEqual({ pattern: "*.ts" });
  });

  test("an unknown tool's input is passed through untouched", () => {
    expect(claudeToolInput("my_mcp_tool", { anything: 1 })).toEqual({ anything: 1 });
  });

  test("the payload carries exactly the five keys the hook scripts parse", () => {
    const payload = toClaudePayload(
      { toolName: "bash", input: { command: "ls" } },
      { cwd: "/repo", sessionId: "sess-1" },
    );
    expect(payload).toEqual({
      hook_event_name: "PreToolUse",
      session_id: "sess-1",
      cwd: "/repo",
      tool_name: "Bash",
      tool_input: { command: "ls" },
    });
  });
});

describe("hook stdout maps onto a gate decision", () => {
  test("silence means allow — every shipped gate stays quiet on the pass path", () => {
    expect(parseHookStdout("")).toEqual({ decision: "allow" });
    expect(parseHookStdout("   \n ")).toEqual({ decision: "allow" });
  });

  test("the Claude PreToolUse deny shape is read, reason included", () => {
    const out = JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "consult memory first",
      },
    });
    expect(parseHookStdout(out)).toEqual({ decision: "deny", reason: "consult memory first" });
  });

  test("an ask decision is read as ask", () => {
    const out = JSON.stringify({
      hookSpecificOutput: { permissionDecision: "ask", permissionDecisionReason: "are you sure" },
    });
    expect(parseHookStdout(out)).toEqual({ decision: "ask", reason: "are you sure" });
  });

  test("the flat Copilot-shaped decision is read too", () => {
    const out = JSON.stringify({ permissionDecision: "deny", permissionDecisionReason: "no" });
    expect(parseHookStdout(out)).toEqual({ decision: "deny", reason: "no" });
  });

  test("valid JSON carrying no decision is an allow, not an error", () => {
    expect(parseHookStdout(JSON.stringify({ systemMessage: "hook skipped" }))).toEqual({
      decision: "allow",
    });
  });

  test("a decision printed after chatter is still found on the last line", () => {
    const out = 'warning: something\n{"hookSpecificOutput":{"permissionDecision":"deny"}}';
    expect(parseHookStdout(out)).toEqual({ decision: "deny", reason: undefined });
  });

  test("unparseable output is null — malformed, which the caller must report, not swallow", () => {
    expect(parseHookStdout("Traceback (most recent call last):")).toBeNull();
  });
});

const deny: GateOutcome = { kind: "decision", decision: "deny", reason: "denied by gate" };
const ask: GateOutcome = { kind: "decision", decision: "ask", reason: "confirm this" };
const allow: GateOutcome = { kind: "decision", decision: "allow" };
const errored: GateOutcome = { kind: "error", reason: "memory_gate.py exited 1" };
const absent: GateOutcome = { kind: "absent", reason: "no .ai-badger/hooks/hooks.json at /repo" };

describe("gate outcomes resolve into one action", () => {
  test("no gates at all is an allow with nothing to report", () => {
    expect(resolve([], { armed: false, hasUI: true })).toEqual({
      action: "allow",
      reason: undefined,
      notices: [],
      autoApproved: false,
    });
  });

  test("a deny blocks and carries its reason", () => {
    const r = resolve([allow, deny], { armed: false, hasUI: true });
    expect(r.action).toBe("block");
    expect(r.reason).toBe("denied by gate");
  });

  test("an ask with a UI asks", () => {
    const r = resolve([ask], { armed: false, hasUI: true });
    expect(r.action).toBe("confirm");
    expect(r.reason).toBe("confirm this");
    expect(r.autoApproved).toBe(false);
  });

  test("deny outranks ask", () => {
    expect(resolve([ask, deny], { armed: false, hasUI: true }).action).toBe("block");
  });
});

describe("an erroring gate is loud and open, never silent and never an approval", () => {
  test("a gate error allows but reports every occurrence", () => {
    const r = resolve([errored, errored], { armed: false, hasUI: true });
    expect(r.action).toBe("allow");
    expect(r.notices).toHaveLength(2);
    expect(r.notices[0]).toContain("memory_gate.py exited 1");
    expect(r.autoApproved).toBe(false);
  });

  test("a missing hooks config allows and reports once", () => {
    const r = resolve([absent], { armed: false, hasUI: true });
    expect(r.action).toBe("allow");
    expect(r.notices).toHaveLength(1);
    expect(r.autoApproved).toBe(false);
  });

  test("a gate error never suppresses another gate's deny", () => {
    const r = resolve([errored, deny], { armed: false, hasUI: true });
    expect(r.action).toBe("block");
    expect(r.notices).toHaveLength(1);
  });

  test("away mode does not turn an error into an approval", () => {
    const r = resolve([errored], { armed: true, hasUI: true });
    expect(r.action).toBe("allow");
    expect(r.autoApproved).toBe(false);
  });

  test("away mode does not turn a missing config into an approval", () => {
    const r = resolve([absent], { armed: true, hasUI: true });
    expect(r.autoApproved).toBe(false);
  });

  test("away mode never overrides a deny", () => {
    expect(resolve([deny], { armed: true, hasUI: true }).action).toBe("block");
  });
});

describe("away mode", () => {
  test("armed, an explicit ask is auto-approved and leaves an audit notice", () => {
    const r = resolve([ask], { armed: true, hasUI: true });
    expect(r.action).toBe("allow");
    expect(r.autoApproved).toBe(true);
    expect(r.notices).toHaveLength(1);
    expect(r.notices[0]).toContain("confirm this");
  });

  test("disarmed and headless, an ask cannot be asked: allowed, and said out loud", () => {
    const r = resolve([ask], { armed: false, hasUI: false });
    expect(r.action).toBe("allow");
    expect(r.autoApproved).toBe(false);
    expect(r.notices).toHaveLength(1);
  });

  test("default off: an unset env is disarmed", () => {
    expect(awayFromEnv({})).toBe(false);
  });

  test("only the exact value 1 arms it", () => {
    expect(awayFromEnv({ AI_BADGER_PI_AWAY: "1" })).toBe(true);
    expect(awayFromEnv({ AI_BADGER_PI_AWAY: "0" })).toBe(false);
    expect(awayFromEnv({ AI_BADGER_PI_AWAY: "true" })).toBe(false);
    expect(awayFromEnv({ AI_BADGER_PI_AWAY: "" })).toBe(false);
  });

  test("default off resolves with no auto-approval on every input", () => {
    const inputs: GateOutcome[][] = [[], [allow], [ask], [deny], [errored], [absent]];
    for (const outcomes of inputs) {
      expect(resolve(outcomes, { armed: false, hasUI: true }).autoApproved).toBe(false);
    }
  });
});
