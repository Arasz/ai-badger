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

/** One PreToolUse entry from `.ai-badger/hooks/hooks.json`: a shell command and its matcher. */
export interface HookCommand {
  matcher?: string;
  command: string;
}

/** The five keys ai-badger's hook scripts actually read from stdin. */
export interface ClaudeHookPayload {
  hook_event_name: "PreToolUse";
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The PreToolUse gates declared in a project's `.ai-badger/hooks/hooks.json`, in file order.
 * Reading the file is what keeps this from becoming a second, drifting copy of the gate list.
 */
export function preToolUseCommands(hooksJson: unknown): HookCommand[] {
  if (!isRecord(hooksJson)) return [];
  const hooks = isRecord(hooksJson.hooks) ? hooksJson.hooks : undefined;
  const groups = hooks?.PreToolUse;
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

/** The commands whose matcher covers `toolName`; a matcher-less entry always runs. */
export function commandsForTool(commands: HookCommand[], toolName: string): string[] {
  return commands
    .filter((entry) => {
      if (!entry.matcher) return true;
      try {
        return new RegExp(`^(?:${entry.matcher})$`).test(toolName);
      } catch {
        return false;
      }
    })
    .map((entry) => entry.command);
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
