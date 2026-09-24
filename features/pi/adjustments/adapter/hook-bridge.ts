/**
 * Pure translation between pi's `tool_call` event and ai-badger's Claude-shaped hook scripts.
 * No I/O lives here so every branch — including the three error paths — is unit-testable.
 */

export type Decision = "allow" | "ask" | "deny";

export interface GateDecision {
  decision: Decision;
  reason?: string;
  /** Claude's top-level `systemMessage`: a line for the user, never for the model. */
  systemMessage?: string;
}

/** What one gate run produced. Errors and absence are outcomes, never decisions. */
export type GateOutcome =
  | { kind: "decision"; decision: Decision; reason?: string; systemMessage?: string }
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

/** The PostToolUse payload: the five pre keys plus the result as a document, under
 * Claude's `tool_response` and the `response` the memory grade hook reads. The shipped
 * post hooks read it as a dict, so it is always one. */
export interface ClaudePostHookPayload extends ClaudeHookPayload<"PostToolUse"> {
  hook_event_name: "PostToolUse";
  tool_response: Record<string, unknown>;
  response: Record<string, unknown>;
}

/** What one post-hook run produced. Post hooks advise, never decide: nothing here can
 * block, ask, or approve a tool call. */
export type PostOutcome =
  | { kind: "ok"; additionalContext?: string; systemMessage?: string }
  | { kind: "error"; reason: string };

export interface PostResolution {
  /** One line per post-hook failure or `systemMessage`, for the UI. */
  notices: string[];
  /** Every `additionalContext`, in hook order, for the model. */
  context: string[];
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

/** Claude's exact-list alphabet: a matcher of only these characters names tools exactly. */
const EXACT_MATCHER = /^[A-Za-z0-9_\-, |]*$/;

/**
 * The commands whose matcher covers `toolName`, under Claude's documented matcher rules:
 * `*`, `""` or no matcher match every tool; a matcher of only letters, digits, `_`, `-`,
 * `,`, `|` and spaces is a list of exact names; anything else is an unanchored JS regex.
 * (Claude before v2.1.195 read hyphenated matchers as regexes, not exact names.)
 * `onBrokenMatcher` receives one line per entry skipped because its regex did not compile.
 */
export function commandsForTool(
  commands: HookCommand[],
  toolName: string,
  onBrokenMatcher?: (reason: string) => void,
  opts?: { mcpSuffix?: boolean },
): string[] {
  // An mcp_-prefixed name is additionally matched by its trailing segments, so a shipped
  // matcher like `memory_search` also fires for the MCP spellings hosts deliver (pi:
  // `mcp_ai-raccoon_memory_search`, Claude: `mcp__ai-raccoon__memory_search`). Each tail
  // is compared whole, so an exact name never matches a substring.
  const candidates = opts?.mcpSuffix ? matcherCandidates(toolName) : [toolName];
  return commands
    .filter((entry) => {
      const matcher = entry.matcher;
      if (matcher === undefined || matcher === "" || matcher === "*") return true;
      if (EXACT_MATCHER.test(matcher)) {
        const names = matcher.split(/[|,]/).map((name) => name.trim()).filter(Boolean);
        return candidates.some((name) => names.includes(name));
      }
      let regex: RegExp;
      try {
        regex = new RegExp(matcher);
      } catch (error) {
        onBrokenMatcher?.(`ai-badger: hook matcher /${matcher}/ is not a valid regex ` +
          `(${String(error)}) — its command is skipped`);
        return false;
      }
      return candidates.some((name) => regex.test(name));
    })
    .map((entry) => entry.command);
}

/** Post-side matcher selection: the same rules plus MCP-suffix awareness, because the
 * shipped PostToolUse entries name MCP tools that pi delivers as `mcp_<server>_<tool>`. */
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

/** The text of a tool result: pi's content array joined on its text blocks (images are
 * skipped); a bare string as-is; anything else as JSON. */
function resultText(content: unknown): string {
  if (content === undefined || content === null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter((block) => isRecord(block) && block.type === "text" && typeof block.text === "string")
      .map((block) => (block as { text: string }).text)
      .join("\n");
  }
  return JSON.stringify(content);
}

/** A tool result as the dict the shipped post hooks read: the text JSON-parsed when it is
 * a JSON object, otherwise `{output: text}`. */
function toolResponse(content: unknown): Record<string, unknown> {
  const text = resultText(content);
  try {
    const parsed: unknown = JSON.parse(text);
    if (isRecord(parsed)) return parsed;
  } catch {
    // plain text
  }
  return { output: text };
}

/** The PostToolUse twin of `toClaudePayload`: same tool shape, plus the result under
 * every key spelling a shipped post hook reads. The pre and post payloads must carry
 * the SAME `session_id` — the marker the post arm records is looked up by the pre arm. */
export function toClaudePostPayload(
  event: { toolName: string; input?: Record<string, unknown>; content?: unknown },
  ctx: { cwd: string; sessionId: string },
): ClaudePostHookPayload {
  const response = toolResponse(event.content);
  return {
    hook_event_name: "PostToolUse",
    session_id: ctx.sessionId,
    cwd: ctx.cwd,
    tool_name: claudeToolName(event.toolName),
    tool_input: claudeToolInput(event.toolName, event.input ?? {}),
    tool_response: response,
    response,
  };
}

/** The pi events the message bus translates, under the Claude spellings the shared
 * delivery script routes on (`message_delivery_hook.py` matches case-insensitively:
 * userpromptsubmit delivers mail, sessionend drops the cursor). pi's delivery seams
 * are `before_agent_start` (run start) and the per-turn `turn_end` event; the close
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
 * unmodified (D31 fail-open).
 *
 * The optional `bus` carries the P2 summary the Python txn merges into
 * `hookSpecificOutput.aiBadgerBus` ({addressed, broadcast} — the delivered batch's counts)
 * or the hook's fail-open marker (`{error: true}`, C2b: guarded_main caught, the cursor may
 * not have moved). One parser, two sides: the Python B6 tests pin the same literal field
 * name and shape; this extraction is the TS half of that contract (QA-3). */
export type DeliveryBus = { addressed: number; broadcast: number } | { error: true };

export type DeliveryOutcome =
  | { kind: "context"; content: string; bus?: DeliveryBus }
  | { kind: "empty"; bus?: DeliveryBus }
  | { kind: "error"; reason: string };

/** The aiBadgerBus field, if it is one of the two shapes the wire contract defines. A
 * malformed summary is treated as ABSENT — the C10 fallback (wake) handles a mail-bearing
 * response without one, and a broken summary must not turn a delivery into a parse error. */
function deliveryBusFrom(inner: unknown): DeliveryBus | undefined {
  if (!isRecord(inner)) return undefined;
  const bus = inner.aiBadgerBus;
  if (!isRecord(bus)) return undefined;
  if (bus.error === true) return { error: true };
  const addressed = bus.addressed;
  const broadcast = bus.broadcast;
  if (
    typeof addressed === "number" && Number.isFinite(addressed) &&
    typeof broadcast === "number" && Number.isFinite(broadcast)
  ) {
    return { addressed, broadcast };
  }
  return undefined;
}

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
  const bus = deliveryBusFrom(inner);
  // The failure marker dominates: guarded_main caught, the txn state is unknown — the
  // outcome must read as "unknown" (never advance the watermark, never inject) and not
  // as a genuine empty inbox (CR-M1).
  if (bus !== undefined && "error" in bus) return { kind: "empty", bus };
  const context = inner?.additionalContext;
  if (typeof context === "string" && context) {
    return bus !== undefined
      ? { kind: "context", content: context, bus }
      : { kind: "context", content: context };
  }
  if (context === "" || context === undefined) return { kind: "empty" };
  return { kind: "error", reason: "delivery script's additionalContext is not a string" };
}

/** The message object pi's `before_agent_start` return seam injects
 * (BeforeAgentStartEventResult.message: {customType, content, display}). */
export interface AgentStartInjection {
  message: { customType: string; content: string; display: boolean };
}

export const AI_BADGER_CUSTOM_TYPE = "ai-badger";

/** One mail envelope as the python delivery prints it into outcome.content:
 * `{sender: {sessionId, projectId}, content, timestamp}` — a shape guard:
 * anything else is not an envelope, never an exception. */
function asMailEnvelope(value: unknown): { senderSession: string | null; timestamp: string | null; content: string | null } | null {
  if (!isRecord(value)) return null;
  const sender = isRecord(value.sender) ? value.sender : null;
  const sessionId = sender !== null && typeof sender.sessionId === "string" ? sender.sessionId : null;
  const timestamp = typeof value.timestamp === "string" ? value.timestamp : null;
  const content = typeof value.content === "string" ? value.content : null;
  if (sessionId === null && timestamp === null && content === null) return null;
  return { senderSession: sessionId, timestamp, content };
}

/** Split raw `ai-badger` message content into card `{head, body}` for the
 * renderer pi gets: envelope JSON → `mail from <short-id> · <ts>` head plus
 * the inner content as body; any other string → body as-is with no head.
 * Empty, blank, non-string, or envelope-without-usable-content splits to
 * undefined (nothing to show). Never throws on any input. */
export function splitMailCard(raw: unknown): { head: string | null; body: string } | undefined {
  try {
    const envelope = typeof raw === "string" ? asMailEnvelope(JSON.parse(raw)) : asMailEnvelope(raw);
    if (envelope !== null && envelope.content !== null && envelope.content.trim() !== "") {
      const who = envelope.senderSession !== null && envelope.senderSession !== "" ? envelope.senderSession.slice(0, 8) : "?";
      const when = envelope.timestamp !== null && envelope.timestamp !== "" ? ` · ${envelope.timestamp}` : "";
      return { head: `mail from ${who}${when}`, body: envelope.content };
    }
    if (envelope !== null) return undefined;
    if (typeof raw === "string" && raw.trim() !== "") return { head: null, body: raw };
    return undefined;
  } catch {
    if (typeof raw === "string" && raw.trim() !== "") return { head: null, body: raw };
    return undefined;
  }
}

export function piMessageFromContext(content: string): AgentStartInjection {
  return {
    message: { customType: AI_BADGER_CUSTOM_TYPE, content, display: true },
  };
}

/** The injected spawn: one delivery-script run for an already-built payload. It resolves
 * every failure mode into a DeliveryOutcome and never rejects — the router's branches
 * stay total. */
export type DeliverySpawn = (payload: ClaudeDeliveryPayload) => Promise<DeliveryOutcome>;

/** What one routed event produced: the custom message to hand pi (before_agent_start's
 * result message, or turn_end's pi.sendMessage) plus the failure lines the caller
 * reports. Nothing here throws. */
export interface DeliveryRouterResult {
  injection?: AgentStartInjection;
  notices: string[];
}

export interface DeliveryRouter {
  beforeAgentStart(ctx: { cwd: string; sessionId: string }): Promise<DeliveryRouterResult>;
  turnEnd(ctx: { cwd: string; sessionId: string }): Promise<DeliveryRouterResult>;
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
 * seam, and `turn_end` hands it to pi.sendMessage as a steer — mail that arrived
 * between LLM calls joins the transcript before the next call (mail between tasks, not
 * after a cancel). Both seams make the mail a session message, never a per-request
 * rewrite: consumed mail must stay on every later call. The close event's spawn is
 * cursor cleanup; its response is discarded — a dead store must not block shutdown,
 * and a close response has nothing pi could inject anyway. Every error becomes a
 * notice (D31).
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

  /** A live read translated into the custom message pi takes at either seam. */
  async function delivery(ctx: { cwd: string; sessionId: string }): Promise<DeliveryRouterResult> {
    const outcome = await liveRead(ctx);
    if (outcome.kind === "context") {
      return { injection: piMessageFromContext(outcome.content), notices: [] };
    }
    if (outcome.kind === "error") {
      return { notices: [`ai-badger: message delivery failed, turn continues — ${outcome.reason}`] };
    }
    return { notices: [] };
  }

  return {
    beforeAgentStart: delivery,
    turnEnd: delivery,

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

/** Post outcomes into UI lines and model context. Carries no action: a post hook can add
 * context to the result, never block or rewrite what the tool produced. */
export function resolvePost(outcomes: PostOutcome[]): PostResolution {
  const notices: string[] = [];
  const context: string[] = [];
  for (const outcome of outcomes) {
    if (outcome.kind === "error") {
      notices.push(`ai-badger: post hook failed, result unaffected — ${outcome.reason}`);
      continue;
    }
    if (outcome.systemMessage) notices.push(outcome.systemMessage);
    if (outcome.additionalContext) context.push(outcome.additionalContext);
  }
  return { notices, context };
}

/** The tool result pi should persist: the tool's own blocks plus one trailing text block
 * of post-hook context, or `undefined` when there is no context to add. */
export function withPostContext<Block>(
  content: readonly Block[] | undefined,
  context: string[],
): Array<Block | { type: "text"; text: string }> | undefined {
  if (context.length === 0) return undefined;
  return [...(content ?? []), { type: "text", text: context.join("\n\n") }];
}

function systemMessageFrom(parsed: Record<string, unknown>): { systemMessage?: string } {
  const message = parsed.systemMessage;
  return typeof message === "string" && message ? { systemMessage: message } : {};
}

function decisionFrom(parsed: unknown): GateDecision {
  if (!isRecord(parsed)) return { decision: "allow" };
  const scope = isRecord(parsed.hookSpecificOutput) ? parsed.hookSpecificOutput : parsed;
  const decision = scope.permissionDecision;
  if (decision === "deny" || decision === "ask" || decision === "allow") {
    const reason = scope.permissionDecisionReason;
    return {
      decision,
      reason: typeof reason === "string" ? reason : undefined,
      ...systemMessageFrom(parsed),
    };
  }
  return { decision: "allow", ...systemMessageFrom(parsed) };
}

function adviceFrom(parsed: unknown): { additionalContext?: string; systemMessage?: string } {
  if (!isRecord(parsed)) return {};
  const scope = isRecord(parsed.hookSpecificOutput) ? parsed.hookSpecificOutput : parsed;
  const context = scope.additionalContext;
  return {
    ...(typeof context === "string" && context ? { additionalContext: context } : {}),
    ...systemMessageFrom(parsed),
  };
}

/** The whole stdout as JSON, else its last non-blank line (some hooks print a warning
 * first); `undefined` when neither parses. */
function lastJson(stdout: string): { value: unknown } | undefined {
  const trimmed = stdout.trim();
  try {
    return { value: JSON.parse(trimmed) };
  } catch {
    // fall through to the last line
  }
  const lines = trimmed.split("\n").filter((line) => line.trim());
  const last = lines[lines.length - 1];
  if (last === undefined) return undefined;
  try {
    return { value: JSON.parse(last) };
  } catch {
    return undefined;
  }
}

/**
 * A gate's stdout as a decision. Silence is allow; valid JSON without a decision is allow;
 * `null` means the output could not be parsed at all — the caller must report that, not swallow it.
 */
export function parseHookStdout(stdout: string): GateDecision | null {
  if (!stdout.trim()) return { decision: "allow" };
  const parsed = lastJson(stdout);
  return parsed === undefined ? null : decisionFrom(parsed.value);
}

/** A post hook's stdout as advice: `hookSpecificOutput.additionalContext` for the model and
 * a top-level `systemMessage` for the user. Anything unparseable advises nothing — post
 * hooks may print, and only their JSON is a contract. */
export function parsePostStdout(stdout: string): { additionalContext?: string; systemMessage?: string } {
  const parsed = lastJson(stdout);
  return parsed === undefined ? {} : adviceFrom(parsed.value);
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
    if (outcome.systemMessage) notices.push(outcome.systemMessage);
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
