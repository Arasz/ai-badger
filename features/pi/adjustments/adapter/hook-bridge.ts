/**
 * Pure translation between pi's `tool_call` event and ai-badger's Claude-shaped hook scripts.
 * No I/O lives here so every branch — including the three error paths — is unit-testable.
 */

export type Decision = "allow" | "ask" | "deny";

export interface GateDecision {
  decision: Decision;
  reason?: string;
}

/** What one gate run produced. Errors and absence are outcomes, never decisions. */
export type GateOutcome =
  | { kind: "decision"; decision: Decision; reason?: string }
  | { kind: "error"; reason: string }
  | { kind: "absent"; reason: string };

/** One PreToolUse/PostToolUse entry from `.ai-badger/hooks/hooks.json`: a shell command and its matcher. */
export interface HookCommand {
  matcher?: string;
  command: string;
}

/** The five keys ai-badger's hook scripts actually read from stdin. The event name is a
 * parameter so the post payload can extend this interface without weakening either arm's
 * literal (default stays "PreToolUse", the shape the pre gates parse). */
export interface ClaudeHookPayload<Event extends "PreToolUse" | "PostToolUse" = "PreToolUse"> {
  hook_event_name: Event;
  session_id: string;
  cwd: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
}

export interface Resolution {
  action: "allow" | "block" | "confirm";
  reason?: string;
  /** One line per error, absence, or away-mode approval. The trail is the audit record. */
  notices: string[];
  autoApproved: boolean;
}

/** The PostToolUse payload: the five pre keys plus the result, which the shipped
 * memory grade hook reads as `payload.get("result") or payload.get("response")`
 * and Claude names `tool_response` — carried under all three spellings it might parse. */
export interface ClaudePostHookPayload extends ClaudeHookPayload<"PostToolUse"> {
  hook_event_name: "PostToolUse";
  tool_response: string;
  response: string;
}

/** What one post-hook run produced. Post hooks are advisory: errors are outcomes to
 * report, never decisions — nothing here can block, ask, or approve a tool call. */
export type PostOutcome = { kind: "ok" } | { kind: "error"; reason: string };

export interface PostResolution {
  /** One line per post-hook failure. The tool result itself is never touched. */
  notices: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The PreToolUse gates declared in a project's `.ai-badger/hooks/hooks.json`, in file order.
 * Reading the file is what keeps this from becoming a second, drifting copy of the gate list.
 */
export function preToolUseCommands(hooksJson: unknown): HookCommand[] {
  return collectCommands(preToolUseGroups(hooksJson));
}

/**
 * The PostToolUse entries (marker recorders, memory telemetry, guards) from the same
 * hooks.json, in file order. Advisory scripts — run for their side effects, never parsed
 * for decisions.
 */
export function postToolUseCommands(hooksJson: unknown): HookCommand[] {
  return collectCommands(postToolUseGroups(hooksJson));
}

function preToolUseGroups(hooksJson: unknown): unknown {
  const hooks = isRecord(hooksJson) && isRecord(hooksJson.hooks) ? hooksJson.hooks : undefined;
  return hooks?.PreToolUse;
}

function postToolUseGroups(hooksJson: unknown): unknown {
  const hooks = isRecord(hooksJson) && isRecord(hooksJson.hooks) ? hooksJson.hooks : undefined;
  return hooks?.PostToolUse;
}

function collectCommands(groups: unknown): HookCommand[] {
  if (!Array.isArray(groups)) return [];

  const out: HookCommand[] = [];
  for (const group of groups) {
    if (!isRecord(group) || !Array.isArray(group.hooks)) continue;
    const matcher = typeof group.matcher === "string" ? group.matcher : undefined;
    for (const entry of group.hooks) {
      if (isRecord(entry) && typeof entry.command === "string") {
        out.push({ matcher, command: entry.command });
      }
    }
  }
  return out;
}

/** The commands whose matcher covers `toolName`; a matcher-less entry always runs.
 * `onBrokenMatcher` receives one line per entry skipped because its regex did not compile —
 * a shipped-matcher typo would otherwise gate nothing, invisibly. */
export function commandsForTool(
  commands: HookCommand[],
  toolName: string,
  onBrokenMatcher?: (reason: string) => void,
  opts?: { mcpSuffix?: boolean },
): string[] {
  // An mcp_-prefixed name is additionally matched against its trailing segments, so a
  // shipped matcher like `memory_search` also fires for the MCP spellings hosts deliver
  // (pi: `mcp_ai-raccoon_memory_search`, Claude: `mcp__ai-raccoon__memory_search`). The
  // segment tails are still anchored (no substring drift), and the full name is always
  // tried first, so plain built-in matchers behave exactly as before.
  const candidates = opts?.mcpSuffix ? matcherCandidates(toolName) : [toolName];
  return commands
    .filter((entry) => {
      if (!entry.matcher) return true;
      let regex: RegExp;
      try {
        regex = new RegExp(`^(?:${entry.matcher})$`);
      } catch (error) {
        onBrokenMatcher?.(`ai-badger: hook matcher /${entry.matcher}/ is not a valid regex ` +
          `(${String(error)}) — its command is skipped`);
        return false;
      }
      return candidates.some((name) => regex.test(name));
    })
    .map((entry) => entry.command);
}

/** Post-side matcher selection: the same anchored rules plus MCP-suffix awareness,
 * because the matchers the shipped PostToolUse entries use (`memory_search`,
 * `export_graph`) name MCP tools that pi delivers as `mcp__<server>__<tool>`. */
export function postCommandsForTool(
  commands: HookCommand[],
  toolName: string,
  onBrokenMatcher?: (reason: string) => void,
): string[] {
  return commandsForTool(commands, toolName, onBrokenMatcher, { mcpSuffix: true });
}

/** The names an mcp_-prefixed tool spelling may be matched by: the full name plus every
 * trailing separator-joined tail of its body, in both host spellings (pi delimits with
 * single underscores, Claude with double), because a server name may itself contain an
 * underscore and the tool part therefore has no fixed position. Non-MCP names yield only
 * themselves. */
function matcherCandidates(toolName: string): string[] {
  const candidates = new Set<string>([toolName]);
  const body = toolName.startsWith("mcp__")
    ? toolName.slice(5)
    : toolName.startsWith("mcp_")
      ? toolName.slice(4)
      : null;
  if (body !== null) {
    for (const separator of ["_", "__"]) {
      const parts = body.split(separator);
      for (let i = 1; i < parts.length; i++) candidates.add(parts.slice(i).join(separator));
    }
  }
  return [...candidates];
}

const TOOL_NAMES: Record<string, string> = {
  bash: "Bash",
  powershell: "Bash",
  read: "Read",
  edit: "MultiEdit",
  write: "Write",
  grep: "Grep",
  find: "Glob",
  ls: "LS",
};

/** pi's tool name under the spelling the shipped hook matchers are written against. */
export function claudeToolName(piToolName: string): string {
  return TOOL_NAMES[piToolName] ?? piToolName;
}

function pick(input: Record<string, unknown>, keys: string[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of keys) {
    if (input[key] !== undefined) out[key] = input[key];
  }
  return out;
}

/**
 * pi's tool input under the key names the guards read (`command`, `file_path`, `pattern`).
 * pi's bash `timeout` is dropped rather than forwarded: Claude's field of that name is
 * milliseconds, and passing a value in the wrong unit is worse than passing none.
 */
export function claudeToolInput(
  piToolName: string,
  input: Record<string, unknown>,
): Record<string, unknown> {
  switch (piToolName) {
    case "bash":
    case "powershell":
      return pick(input, ["command"]);
    case "read": {
      const { path, ...rest } = input;
      return { file_path: path, ...rest };
    }
    case "write": {
      const { path, ...rest } = input;
      return { file_path: path, ...rest };
    }
    case "edit": {
      const edits = Array.isArray(input.edits) ? input.edits : [];
      return {
        file_path: input.path,
        edits: edits.map((edit) =>
          isRecord(edit) ? { old_string: edit.oldText, new_string: edit.newText } : edit,
        ),
      };
    }
    case "grep":
      return pick(input, ["pattern", "path", "glob"]);
    case "find":
      return pick(input, ["pattern", "path"]);
    case "ls":
      return pick(input, ["path"]);
    default:
      return input;
  }
}

export function toClaudePayload(
  event: { toolName: string; input: Record<string, unknown> },
  ctx: { cwd: string; sessionId: string },
): ClaudeHookPayload {
  return {
    hook_event_name: "PreToolUse",
    session_id: ctx.sessionId,
    cwd: ctx.cwd,
    tool_name: claudeToolName(event.toolName),
    tool_input: claudeToolInput(event.toolName, event.input),
  };
}

/** The PostToolUse twin of `toClaudePayload`: same tool shape, plus the result under
 * every key spelling a shipped post hook reads. The pre and post payloads must carry
 * the SAME `session_id` — the marker the post arm records is looked up by the pre arm. */
export function toClaudePostPayload(
  event: { toolName: string; input?: Record<string, unknown>; content?: unknown },
  ctx: { cwd: string; sessionId: string },
): ClaudePostHookPayload {
  const content = event.content === undefined || event.content === null
    ? ""
    : typeof event.content === "string"
      ? event.content
      : JSON.stringify(event.content);
  return {
    hook_event_name: "PostToolUse",
    session_id: ctx.sessionId,
    cwd: ctx.cwd,
    tool_name: claudeToolName(event.toolName),
    tool_input: claudeToolInput(event.toolName, event.input ?? {}),
    tool_response: content,
    response: content,
  };
}

/** The pi events the message bus translates, under the Claude spellings the shared
 * delivery script routes on (`message_delivery_hook.py` matches case-insensitively:
 * userpromptsubmit delivers mail, sessionend drops the cursor). pi's delivery seams
 * are `before_agent_start` (run start) and the per-turn `context` event; the close
 * event is `session_shutdown`. There is no start-spawn: a session that never turns
 * fires no delivery event, so no cursor row is written and mail survives for the
 * session that does turn. */
export type PiDeliveryEvent = "before_agent_start" | "session_shutdown";
export type ClaudeDeliveryEvent = "UserPromptSubmit" | "SessionEnd";

export const PI_DELIVERY_EVENT_MAP: Record<PiDeliveryEvent, ClaudeDeliveryEvent> = {
  before_agent_start: "UserPromptSubmit",
  session_shutdown: "SessionEnd",
};

/** The delivery payload: the three keys the shared script reads — no tool fields, which
 * is why it is its own interface and not a ClaudeHookPayload variant. */
export interface ClaudeDeliveryPayload {
  hook_event_name: ClaudeDeliveryEvent;
  session_id: string;
  cwd: string;
}

export function toClaudeDeliveryPayload(
  piEvent: PiDeliveryEvent,
  ctx: { cwd: string; sessionId: string },
): ClaudeDeliveryPayload {
  return {
    hook_event_name: PI_DELIVERY_EVENT_MAP[piEvent],
    session_id: ctx.sessionId,
    cwd: ctx.cwd,
  };
}

/** One delivery-script run, parsed from its stdout. Empty and error are outcomes, never
 * exceptions — the same discipline as GateOutcome: `empty` means "the store answered, the
 * inbox is empty" (parseable `{}`), `error` means this firing failed and the turn goes on
 * unmodified (D31 fail-open). */
export type DeliveryOutcome =
  | { kind: "context"; content: string }
  | { kind: "empty" }
  | { kind: "error"; reason: string };

/** The delivery script's stdout (one JSON document: `{}`, or hookSpecificOutput with the
 * rendered mail in `additionalContext`) as an outcome. Anything unparseable is an error
 * outcome — mail content is multiline JSON-escaped, so the whole body always parses. */
export function parseDeliveryStdout(stdout: string): DeliveryOutcome {
  const trimmed = stdout.trim();
  if (!trimmed) return { kind: "error", reason: "delivery script printed nothing" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch (error) {
    return {
      kind: "error",
      reason: `delivery script printed output that is not JSON: ${trimmed.slice(0, 200)} (${String(error)})`,
    };
  }
  if (!isRecord(parsed) || Object.keys(parsed).length === 0) return { kind: "empty" };
  const inner = isRecord(parsed.hookSpecificOutput) ? parsed.hookSpecificOutput : undefined;
  const context = inner?.additionalContext;
  if (typeof context === "string" && context) return { kind: "context", content: context };
  if (context === "" || context === undefined) return { kind: "empty" };
  return { kind: "error", reason: "delivery script's additionalContext is not a string" };
}

/** The message object pi's `before_agent_start` return seam injects
 * (BeforeAgentStartEventResult.message: {customType, content, display}). */
export interface AgentStartInjection {
  message: { customType: string; content: string; display: boolean };
}

export const AI_BADGER_CUSTOM_TYPE = "ai-badger";

export function piMessageFromContext(content: string): AgentStartInjection {
  return {
    message: { customType: AI_BADGER_CUSTOM_TYPE, content, display: true },
  };
}

/** The message object pi's per-turn `context` seam appends to the message array the
 * handler returns ({ messages }): one custom message in the full CustomMessage shape
 * (role "custom", timestamp) — pi renders it and carries it to the LLM like any
 * custom message. */
export interface ContextInjection {
  message: { role: "custom"; customType: string; content: string; display: boolean; timestamp: number };
}

export function piContextMessageFromContext(content: string): ContextInjection {
  return {
    message: {
      role: "custom",
      customType: AI_BADGER_CUSTOM_TYPE,
      content,
      display: true,
      timestamp: Date.now(),
    },
  };
}

/** The injected spawn: one delivery-script run for an already-built payload. It resolves
 * every failure mode into a DeliveryOutcome and never rejects — the router's branches
 * stay total. */
export type DeliverySpawn = (payload: ClaudeDeliveryPayload) => Promise<DeliveryOutcome>;

/** What one routed event produced: pi's result-message injection (before_agent_start)
 * plus the failure lines the caller reports. Nothing here throws. */
export interface DeliveryRouterResult {
  injection?: AgentStartInjection;
  notices: string[];
}

/** The per-turn seam's result: the same outcome translated into the message object the
 * caller appends to the `context` event's message array. */
export interface DeliveryContextResult {
  injection?: ContextInjection;
  notices: string[];
}

export interface DeliveryRouter {
  beforeAgentStart(ctx: { cwd: string; sessionId: string }): Promise<DeliveryRouterResult>;
  context(ctx: { cwd: string; sessionId: string }): Promise<DeliveryContextResult>;
  sessionShutdown(ctx: { cwd: string; sessionId: string }): Promise<DeliveryRouterResult>;
}

/** The subscription state machine behind the message-bus handlers.
 *
 * Start-spawn is deferred (D4): there is no `session_start` delivery. A session whose
 * runtime never reaches a turn spawns nothing — no store hit, no cursor row — and its
 * mail survives for the session that does turn (the store's 30-minute first-read gate
 * applies from that turn). Delivery runs at two seams, both the same unconditional
 * live read with the store's exactly-once transaction advancing the cursor once per
 * consumed message: `before_agent_start` returns the mail through pi's result-message
 * seam, and the per-turn `context` event appends it to the message array pi hands the
 * handler — mail that arrived between LLM calls lands at the next call (mail between
 * tasks, not after a cancel). The close event's spawn is cursor cleanup; its response
 * is discarded — a dead store must not block shutdown, and a close response has
 * nothing pi could inject anyway. Every error becomes a notice (D31).
 */
export function createDeliveryRouter(spawn: DeliverySpawn): DeliveryRouter {
  /** One unconditional live read: the payload routes as UserPromptSubmit, a delivery
   * event. A rejecting spawn is an error outcome — the router's branches stay total. */
  async function liveRead(ctx: { cwd: string; sessionId: string }): Promise<DeliveryOutcome> {
    try {
      return await spawn(toClaudeDeliveryPayload("before_agent_start", ctx));
    } catch (error) {
      return { kind: "error", reason: String(error) };
    }
  }

  return {
    // Run start: one unconditional live read through pi's result-message seam.
    async beforeAgentStart(ctx) {
      const outcome = await liveRead(ctx);
      if (outcome.kind === "context") {
        return { injection: piMessageFromContext(outcome.content), notices: [] };
      }
      if (outcome.kind === "error") {
        return { notices: [`ai-badger: message delivery failed, turn continues — ${outcome.reason}`] };
      }
      return { notices: [] };
    },

    // Per-turn seam inside the agent loop: the same live read, its mail appended to
    // the message array pi handed over — mail that arrived between LLM calls lands here.
    async context(ctx) {
      const outcome = await liveRead(ctx);
      if (outcome.kind === "context") {
        return { injection: piContextMessageFromContext(outcome.content), notices: [] };
      }
      if (outcome.kind === "error") {
        return { notices: [`ai-badger: message delivery failed, turn continues — ${outcome.reason}`] };
      }
      return { notices: [] };
    },

    async sessionShutdown(ctx) {
      try {
        await spawn(toClaudeDeliveryPayload("session_shutdown", ctx));
      } catch (error) {
        return { notices: [`ai-badger: cursor cleanup failed — ${String(error)}`] };
      }
      return { notices: [] };
    },
  };
}

/** The session id every hook payload carries. pi's own session id (via the session
 * manager) is the authority; `PI_SESSION_ID` is the fallback; empty is the documented
 * last resort. The empty string is why the empty-session contract exists in the gate:
 * an empty id cannot record a marker or count denials, so a real id matters wherever
 * pi can provide one. Never throws — an older build's session manager shape must not
 * take down the payload. */
export function resolveSessionId(
  ctx: { sessionManager?: { getSessionId?: () => string } },
  env: Record<string, string | undefined>,
): string {
  try {
    const id = ctx.sessionManager?.getSessionId?.();
    if (typeof id === "string" && id) return id;
  } catch {
    // fall through to the env fallback
  }
  return env.PI_SESSION_ID ?? "";
}

/** Post outcomes into user-facing lines. Deliberately carries no action: a post hook
 * failure is reported and the tool result is left exactly as the tool produced it. */
export function resolvePost(outcomes: PostOutcome[]): PostResolution {
  const notices = outcomes
    .filter((outcome) => outcome.kind === "error")
    .map((outcome) => `ai-badger: post hook failed, result unaffected — ${outcome.reason}`);
  return { notices };
}

function decisionFrom(parsed: unknown): GateDecision {
  if (!isRecord(parsed)) return { decision: "allow" };
  const scope = isRecord(parsed.hookSpecificOutput) ? parsed.hookSpecificOutput : parsed;
  const decision = scope.permissionDecision;
  if (decision === "deny" || decision === "ask" || decision === "allow") {
    const reason = scope.permissionDecisionReason;
    return { decision, reason: typeof reason === "string" ? reason : undefined };
  }
  return { decision: "allow" };
}

/**
 * A gate's stdout as a decision. Silence is allow; valid JSON without a decision is allow;
 * `null` means the output could not be parsed at all — the caller must report that, not swallow it.
 */
export function parseHookStdout(stdout: string): GateDecision | null {
  const trimmed = stdout.trim();
  if (!trimmed) return { decision: "allow" };
  try {
    return decisionFrom(JSON.parse(trimmed));
  } catch {
    // Some hooks print a warning before their decision; the decision is the last line.
  }
  const lines = trimmed.split("\n").filter((line) => line.trim());
  const last = lines[lines.length - 1];
  if (last === undefined) return null;
  try {
    return decisionFrom(JSON.parse(last));
  } catch {
    return null;
  }
}

/**
 * The single action a tool call takes from every gate's outcome.
 * Deny wins; only an explicit "ask" is ever auto-approved by away mode.
 */
export function resolve(
  outcomes: GateOutcome[],
  session: { armed: boolean; hasUI: boolean },
): Resolution {
  const notices: string[] = [];
  let denial: GateDecision | undefined;
  let question: GateDecision | undefined;

  for (const outcome of outcomes) {
    if (outcome.kind === "error") {
      notices.push(`ai-badger: hook gate failed, tool call allowed — ${outcome.reason}`);
      continue;
    }
    if (outcome.kind === "absent") {
      notices.push(`ai-badger: no hook gates here, tool call allowed — ${outcome.reason}`);
      continue;
    }
    if (outcome.decision === "deny" && !denial) {
      denial = { decision: "deny", reason: outcome.reason };
    } else if (outcome.decision === "ask" && !question) {
      question = { decision: "ask", reason: outcome.reason };
    }
  }

  if (denial) {
    return { action: "block", reason: denial.reason, notices, autoApproved: false };
  }
  if (question) {
    const reason = question.reason ?? "(no reason given)";
    if (session.armed) {
      notices.push(`ai-badger: away mode auto-approved — ${reason}`);
      return { action: "allow", notices, autoApproved: true };
    }
    if (!session.hasUI) {
      notices.push(
        `ai-badger: hook gate asked but this run has no UI, tool call allowed — ${reason}`,
      );
      return { action: "allow", notices, autoApproved: false };
    }
    return { action: "confirm", reason: question.reason, notices, autoApproved: false };
  }
  return { action: "allow", notices, autoApproved: false };
}

/** Away mode is off unless the env says exactly `1`. */
export function awayFromEnv(env: Record<string, string | undefined>): boolean {
  return env.AI_BADGER_PI_AWAY === "1";
}

export interface AwayState {
  armed(): boolean;
  /** Flip arming and return the new value. */
  toggle(): boolean;
}

/**
 * Session-scoped away-mode state, seeded from the environment and held nowhere else.
 * Nothing is persisted, so arming can never survive the process it was set in.
 */
export function createAwayState(env: Record<string, string | undefined>): AwayState {
  let value = awayFromEnv(env);
  return {
    armed: () => value,
    toggle: () => {
      value = !value;
      return value;
    },
  };
}
