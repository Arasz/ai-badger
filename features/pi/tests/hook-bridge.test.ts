import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import {
  awayFromEnv,
  claudeToolInput,
  claudeToolName,
  commandsForTool,
  parseDeliveryStdout,
  parseHookStdout,
  postCommandsForTool,
  postToolUseCommands,
  preToolUseCommands,
  resolve,
  resolvePost,
  resolveSessionId,
  toClaudePayload,
  toClaudePostPayload,
  type GateOutcome,
  type PostOutcome,
} from "../adjustments/adapter/hook-bridge.ts";
import * as bridge from "../adjustments/adapter/hook-bridge.ts";

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

describe("PostToolUse commands come from hooks.json the same way", () => {
  const hooksJson = {
    hooks: {
      PreToolUse: [
        { matcher: "Grep|Glob|Bash", hooks: [{ type: "command", command: "python3 pre.py" }] },
      ],
      PostToolUse: [
        { matcher: "memory_search", hooks: [{ type: "command", command: "python3 marker.py" }] },
        { matcher: "Read|ReadFile", hooks: [{ type: "command", command: "python3 grade.py" }] },
        { hooks: [{ type: "command", command: "python3 always-post.py" }] },
      ],
      Stop: [{ hooks: [{ type: "command", command: "python3 stop.py" }] }],
    },
  };

  test("only PostToolUse entries are collected — pre and stop entries stay out", () => {
    const commands = postToolUseCommands(hooksJson);
    expect(commands.map((c) => c.command)).toEqual([
      "python3 marker.py",
      "python3 grade.py",
      "python3 always-post.py",
    ]);
  });

  test("a missing or malformed hooks.json yields no post hooks rather than throwing", () => {
    expect(postToolUseCommands(null)).toEqual([]);
    expect(postToolUseCommands({ hooks: { PostToolUse: 7 } })).toEqual([]);
  });

  test("a matcher-less post entry always runs, like on the pre side", () => {
    const commands = postToolUseCommands(hooksJson);
    expect(postCommandsForTool(commands, "mcp__x__memory_search")).toContain(
      "python3 always-post.py",
    );
    expect(postCommandsForTool(commands, "Read")).toContain("python3 always-post.py");
  });
});

describe("post matchers also recognize mcp__-prefixed tool names by their bare suffix", () => {
  const commands = [{ matcher: "memory_search", command: "python3 marker.py" }];

  test("the shipped `memory_search` matcher fires for mcp__ai-raccoon__memory_search", () => {
    expect(postCommandsForTool(commands, "mcp__ai-raccoon__memory_search")).toEqual([
      "python3 marker.py",
    ]);
  });

  test("pi's single-underscore MCP spelling fires too — that is what pi actually delivers", () => {
    expect(postCommandsForTool(commands, "mcp_ai-raccoon_memory_search")).toEqual([
      "python3 marker.py",
    ]);
    expect(postCommandsForTool(commands, "mcp_ai_raccoon_memory_search")).toEqual([
      "python3 marker.py",
    ]);
  });

  test("anchored semantics survive: a suffix match is not a substring match", () => {
    expect(postCommandsForTool(commands, "memory_search_extra")).toEqual([]);
    expect(postCommandsForTool(commands, "not_memory_search")).toEqual([]);
    expect(postCommandsForTool(commands, "mcp_ai-raccoon_memory_search_extra")).toEqual([]);
  });

  test("a non-MCP tool name is matched exactly as on the pre side", () => {
    expect(postCommandsForTool(commands, "memory_search")).toEqual(["python3 marker.py"]);
    expect(postCommandsForTool([{ matcher: "Bash", command: "x.py" }], "BashOutput")).toEqual([]);
  });

  test("an unparseable post matcher is skipped and reported like a pre one", () => {
    const broken: string[] = [];
    const out = postCommandsForTool(
      [{ matcher: "([", command: "x.py" }],
      "Bash",
      (reason) => broken.push(reason),
    );
    expect(out).toEqual([]);
    expect(broken).toHaveLength(1);
    expect(broken[0]).toContain("([");
  });
});

describe("the post payload carries what the shipped PostToolUse hooks parse", () => {
  test("exact key set: event name, ids, tool shape, and the result mirror the grade hook reads", () => {
    const payload = toClaudePostPayload(
      { toolName: "bash", input: { command: "ls" }, content: "out" },
      { cwd: "/repo", sessionId: "sess-1" },
    );
    expect(payload).toEqual({
      hook_event_name: "PostToolUse",
      session_id: "sess-1",
      cwd: "/repo",
      tool_name: "Bash",
      tool_input: { command: "ls" },
      tool_response: { output: "out" },
      response: { output: "out" },
    });
  });

  test("pi's real content array: a JSON text block arrives as the parsed document", () => {
    const payload = toClaudePostPayload(
      {
        toolName: "mcp_ai-raccoon_memory_search",
        input: {},
        content: [{ type: "text", text: '{"results":[]}' }],
      },
      { cwd: "/repo", sessionId: "s" },
    );
    expect(payload.tool_response).toEqual({ results: [] });
    expect(payload.response).toEqual({ results: [] });
  });

  test("plain text arrives as {output: text}; image blocks are skipped, text blocks joined", () => {
    const payload = toClaudePostPayload(
      {
        toolName: "bash",
        input: {},
        content: [
          { type: "text", text: "line one" },
          { type: "image", data: "AAAA", mimeType: "image/png" },
          { type: "text", text: "line two" },
        ],
      },
      { cwd: "/repo", sessionId: "s" },
    );
    expect(payload.tool_response).toEqual({ output: "line one\nline two" });
  });

  test("JSON that is not an object stays text: the hooks read a dict, never a list", () => {
    const payload = toClaudePostPayload(
      { toolName: "my_mcp_tool", input: {}, content: [{ type: "text", text: "[1,2]" }] },
      { cwd: "/repo", sessionId: "s" },
    );
    expect(payload.tool_response).toEqual({ output: "[1,2]" });
  });

  test("a missing result is an empty output, still a dict", () => {
    const missing = toClaudePostPayload(
      { toolName: "read", input: {} },
      { cwd: "/repo", sessionId: "s" },
    );
    expect(missing.tool_response).toEqual({ output: "" });
    expect(missing.response).toEqual({ output: "" });
  });

  test("tool input goes through the same claude-shape mapping as the pre payload", () => {
    const payload = toClaudePostPayload(
      { toolName: "read", input: { path: "/a/b.py" }, content: "x" },
      { cwd: "/repo", sessionId: "s" },
    );
    expect(payload.tool_input).toEqual({ file_path: "/a/b.py" });
  });
});

describe("session id resolution: sessionManager first, then env, never a crash", () => {
  test("ctx.sessionManager.getSessionId() wins — marker and denials must key on pi's own id", () => {
    expect(resolveSessionId({ sessionManager: { getSessionId: () => "pi-1" } }, {})).toBe("pi-1");
  });

  test("falls back to PI_SESSION_ID when the manager is missing, empty, or throws", () => {
    const env = { PI_SESSION_ID: "env-1" };
    expect(resolveSessionId({}, env)).toBe("env-1");
    expect(resolveSessionId({ sessionManager: {} }, env)).toBe("env-1");
    expect(resolveSessionId({ sessionManager: { getSessionId: () => "" } }, env)).toBe("env-1");
    expect(
      resolveSessionId(
        {
          sessionManager: {
            getSessionId: () => {
              throw new Error("old build");
            },
          },
        },
        env,
      ),
    ).toBe("env-1");
  });

  test("an empty string — not undefined — when nothing is available", () => {
    expect(resolveSessionId({}, {})).toBe("");
  });
});

describe("post outcomes are advisory: reported, never blocking", () => {
  const postError: PostOutcome = { kind: "error", reason: "marker.py exited 1" };

  test("a clean run reports nothing", () => {
    expect(resolvePost([])).toEqual({ notices: [], context: [] });
    expect(resolvePost([{ kind: "ok" }])).toEqual({ notices: [], context: [] });
  });

  test("every failure is a notice — and there is no action key to misuse for blocking", () => {
    const r = resolvePost([postError, postError]);
    expect(r.notices).toHaveLength(2);
    expect(r.notices[0]).toContain("marker.py exited 1");
    expect(Object.keys(r).sort()).toEqual(["context", "notices"]);
  });

  test("additionalContext is collected for the model; systemMessage becomes a notice", () => {
    const r = resolvePost([
      { kind: "ok", additionalContext: "commit now" },
      { kind: "ok", systemMessage: "heads up" },
      { kind: "ok", additionalContext: "tests failed" },
    ]);
    expect(r.context).toEqual(["commit now", "tests failed"]);
    expect(r.notices).toEqual(["heads up"]);
  });
});

describe("post hook stdout carries advice, never a decision", () => {
  test("hookSpecificOutput.additionalContext and a top-level systemMessage are read", () => {
    expect(
      bridge.parsePostStdout(
        '{"systemMessage":"shown","hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"for the model"}}',
      ),
    ).toEqual({ additionalContext: "for the model", systemMessage: "shown" });
  });

  test("silence, chatter and unparseable output advise nothing", () => {
    expect(bridge.parsePostStdout("")).toEqual({});
    expect(bridge.parsePostStdout("not json at all")).toEqual({});
    expect(bridge.parsePostStdout('{"hookSpecificOutput":{"additionalContext":7}}')).toEqual({});
  });

  test("advice printed after chatter is still found on the last line", () => {
    expect(bridge.parsePostStdout('warming up\n{"hookSpecificOutput":{"additionalContext":"X"}}')).toEqual({
      additionalContext: "X",
    });
  });
});

describe("post-hook context is appended to the tool result pi persists", () => {
  const original = [{ type: "text" as const, text: "file body" }];

  test("context becomes one trailing text block after the tool's own content", () => {
    expect(bridge.withPostContext(original, ["one", "two"])).toEqual([
      { type: "text", text: "file body" },
      { type: "text", text: "one\n\ntwo" },
    ]);
  });

  test("no context leaves the result untouched", () => {
    expect(bridge.withPostContext(original, [])).toBeUndefined();
  });

  test("a missing content array still carries the context", () => {
    expect(bridge.withPostContext(undefined, ["X"])).toEqual([{ type: "text", text: "X" }]);
  });
});

describe("a gate's systemMessage reaches the UI next to its decision", () => {
  test("parsed alongside a decision, and alone", () => {
    expect(parseHookStdout('{"systemMessage":"dirty tree elsewhere"}')).toEqual({
      decision: "allow",
      systemMessage: "dirty tree elsewhere",
    });
  });

  test("resolve reports it as a notice without changing the action", () => {
    const r = resolve(
      [{ kind: "decision", decision: "allow", systemMessage: "dirty tree elsewhere" }],
      { armed: false, hasUI: true },
    );
    expect(r.action).toBe("allow");
    expect(r.notices).toEqual(["dirty tree elsewhere"]);
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
    expect(parseHookStdout(JSON.stringify({ continue: true }))).toEqual({ decision: "allow" });
    expect(parseHookStdout(JSON.stringify({ systemMessage: "hook skipped" }))).toEqual({
      decision: "allow",
      systemMessage: "hook skipped",
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

// ---------------------------------------------------------------------------
// P3 (aib-pi-message-bus-push-delivery) — the delivery stdout's FOURTH parse
// shape: the P2 summary rides in hookSpecificOutput.aiBadgerBus, and the hook's
// fail-open net (C2b) prints `aiBadgerBus: {error: true}` on internal failure.
// One parser, two sides: the Python B6 pins the same literal field name/shape,
// this pins the TS extraction (QA-3's two-sided contract).
// ---------------------------------------------------------------------------

describe("parseDeliveryStdout extracts the aiBadgerBus summary alongside the mail document", () => {
  test("a mail response carrying the summary yields kind context plus the extracted counts", () => {
    const out = parseDeliveryStdout(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "UserPromptSubmit",
          additionalContext: "mail body",
          aiBadgerBus: { addressed: 2, broadcast: 1 },
        },
      }),
    );
    expect(out).toEqual({ kind: "context", content: "mail body", bus: { addressed: 2, broadcast: 1 } });
  });

  test("a summary with zero counts is still carried — the counts are data, not absence", () => {
    const out = parseDeliveryStdout(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "UserPromptSubmit",
          additionalContext: "mail body",
          aiBadgerBus: { addressed: 0, broadcast: 0 },
        },
      }),
    );
    expect(out).toEqual({ kind: "context", content: "mail body", bus: { addressed: 0, broadcast: 0 } });
  });

  test("the failure marker (C2b) parses as an empty outcome carrying the error marker", () => {
    const out = parseDeliveryStdout(
      JSON.stringify({ hookSpecificOutput: { aiBadgerBus: { error: true } } }),
    );
    expect(out).toEqual({ kind: "empty", bus: { error: true } });
  });

  test("a response without aiBadgerBus keeps the legacy shapes byte-for-byte", () => {
    expect(parseDeliveryStdout("{}")).toEqual({ kind: "empty" });
    expect(
      parseDeliveryStdout(
        JSON.stringify({ hookSpecificOutput: { hookEventName: "UserPromptSubmit", additionalContext: "m" } }),
      ),
    ).toEqual({ kind: "context", content: "m" });
  });

  test("a malformed summary is treated as absent, never as an error outcome", () => {
    const out = parseDeliveryStdout(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "UserPromptSubmit",
          additionalContext: "m",
          aiBadgerBus: { addressed: "many" },
        },
      }),
    );
    expect(out).toEqual({ kind: "context", content: "m" });
  });
});

describe("the shipped PostToolUse matchers fire on the MCP names pi delivers", () => {
  // The framework's own hooks.json, read from this repo; a mirror without it skips loudly.
  const source = join(import.meta.dir, "..", "..", "common", "hooks", "hooks.json");
  const present = existsSync(source);
  const shipped = present ? postToolUseCommands(JSON.parse(readFileSync(source, "utf-8"))) : [];
  const fired = (tool: string) => postCommandsForTool(shipped, tool).join("\n");

  test.skipIf(!present)("memory_search fires the marker and the grade hook", () => {
    for (const tool of ["mcp_ai-raccoon_memory_search", "mcp__ai-raccoon__memory_search"]) {
      expect(fired(tool)).toContain("memory_first_gate_post_hook.py");
      expect(fired(tool)).toContain("memory_grade_hook.py");
    }
  });

  test.skipIf(!present)("export_graph fires the semantica autosave", () => {
    expect(fired("mcp_semantica_export_graph")).toContain("semantica_export_autosave_hook.py");
    expect(fired("mcp__semantica__export_graph")).toContain("semantica_export_autosave_hook.py");
  });

  test.skipIf(!present)("a longer tool name from the same server fires nothing", () => {
    expect(fired("mcp_ai-raccoon_memory_search_extra")).toBe("");
    expect(fired("mcp_semantica_export_graph_v2")).toBe("");
  });
});

describe("matchers follow Claude's documented semantics, judged by the shared Python rule", () => {
  // The verdicts come from tests/hook_matcher_rules.py (claude_matches), so the TS bridge and
  // the Python wiring tests answer from one rule. Each tool is tried in its Claude spelling
  // and in the spelling pi delivers; both must fire exactly when Claude would fire.
  const repo = join(import.meta.dir, "..", "..", "..");
  const present = existsSync(join(repo, "tests", "hook_matcher_rules.py"));

  const matchers: Array<string | undefined> = [
    "^(mcp__.+__|.+-)?memory_search$",
    "^(mcp__.+__|.+-)?export_graph$",
    "Read|ReadFile",
    "*",
    "",
    undefined,
    "Edit|Write",
    "Edit, Write",
    "web-fetch",
    "ai-raccoon-memory_search",
  ];
  // [Claude spelling, pi spelling]
  const tools: Array<[string, string]> = [
    ["mcp__ai-raccoon__memory_search", "mcp_ai-raccoon_memory_search"],
    ["mcp__ai-raccoon__memory_search_extra", "mcp_ai-raccoon_memory_search_extra"],
    ["mcp__semantica__export_graph", "mcp_semantica_export_graph"],
    ["mcp__semantica__export_graph_v2", "mcp_semantica_export_graph_v2"],
    ["Read", "read"],
    ["Write", "write"],
    ["MultiEdit", "edit"],
    ["Bash", "bash"],
    ["web-fetch", "web-fetch"],
    ["web-fetcher", "web-fetcher"],
  ];

  /** claude_matches(matcher, claudeSpelling) for every matcher × tool, in row order. */
  function claudeVerdicts(): boolean[] {
    const cases = matchers.flatMap((matcher) => tools.map(([claude]) => [matcher ?? null, claude]));
    const run = Bun.spawnSync(
      [
        "python3",
        "-c",
        "import json,sys; sys.path.insert(0, sys.argv[1]); from hook_matcher_rules import claude_matches; " +
          "print(json.dumps([claude_matches(m, t) for m, t in json.load(sys.stdin)]))",
        join(repo, "tests"),
      ],
      { stdin: new TextEncoder().encode(JSON.stringify(cases)) },
    );
    if (run.exitCode !== 0) throw new Error(`hook_matcher_rules.py failed: ${run.stderr.toString()}`);
    return JSON.parse(run.stdout.toString());
  }

  test.skipIf(!present)("pre and post sides fire on both spellings exactly when Claude does", () => {
    const expected = claudeVerdicts();
    const mismatches: string[] = [];
    let index = 0;
    for (const matcher of matchers) {
      const entry = [{ matcher, command: "hook.py" }];
      for (const [claude, pi] of tools) {
        const want = expected[index++];
        const broken: string[] = [];
        const seen = {
          "post/claude": postCommandsForTool(entry, claude, (r) => broken.push(r)).length > 0,
          "post/pi": postCommandsForTool(entry, claudeToolName(pi), (r) => broken.push(r)).length > 0,
          "pre/claude": commandsForTool(entry, claude, (r) => broken.push(r)).length > 0,
        };
        for (const [side, got] of Object.entries(seen)) {
          if (got !== want) {
            mismatches.push(`${JSON.stringify(matcher)} ${side} ${claude}/${pi}: got ${got}, Claude ${want}`);
          }
        }
        if (broken.length) mismatches.push(`${JSON.stringify(matcher)} reported broken: ${broken[0]}`);
      }
    }
    expect(mismatches).toEqual([]);
  });

  test.skipIf(!present)("the rule itself: * matches all, a hyphenated name is exact", () => {
    const expected = claudeVerdicts();
    const at = (matcher: string | undefined, tool: string) =>
      expected[matchers.indexOf(matcher) * tools.length + tools.findIndex(([c]) => c === tool)];
    expect(at("*", "Bash")).toBe(true);
    expect(at("web-fetch", "web-fetch")).toBe(true);
    expect(at("web-fetch", "web-fetcher")).toBe(false);
  });
});
