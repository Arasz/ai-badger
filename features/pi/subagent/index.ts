/**
 * ai-badger subagent for pi: one delegation tool over the personas ai-badger scaffolds into
 * `<cwd>/.pi/agents/*.md` (written by `features/pi/adjustments/adjust_agents.py`).
 *
 * Installed user-scope at `~/.pi/agent/extensions/ai-badger-subagent/index.ts`, and it reads the
 * project's agent files ITSELF through `node:fs`. That is the whole trick, and it must not be
 * "simplified" into pi's own resource loader later: project-local resources are trust-gated, and
 * pi's settings docs state that `-p`, `--mode json` and `--mode rpc` ignore project resources
 * entirely without a saved trust decision. A user-scope extension reading files with `fs` is not
 * subject to that gate, which is what makes the personas live in the headless runs ai-badger's
 * delegation map depends on.
 *
 * pi's 35 KB subagent example is deliberately not vendored: its parallel streaming, cost
 * accounting and workflow prompts are not what the delegation map asks for, and copying a third
 * party's example owes us its maintenance forever.
 *
 * Every failure is loud (`ctx.ui.notify`) and degrades to a reported result — a missing agents
 * directory, an unreadable or unparseable persona, an unknown agent name, or a failed child
 * process. Silent failure is the defect class this extension exists to end.
 */

import { spawn } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";
import { type ExtensionAPI, parseFrontmatter } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

/** The tool the LLM calls. Also excluded from the child, so a delegation cannot re-delegate. */
export const TOOL_NAME = "delegate";

/** Where adjust_agents.py writes, relative to the project root. */
export const AGENTS_DIR = [".pi", "agents"];

/** Output kept from the child, so one runaway subagent cannot flood the parent's context. */
export const MAX_OUTPUT_BYTES = 64 * 1024;

export interface Persona {
  name: string;
  description: string;
  /** The file body below the frontmatter — appended to the child's system prompt. */
  systemPrompt: string;
  filePath: string;
}

/** What one agents directory holds: the personas that parsed, and a line per file that did not. */
export interface PersonaScan {
  personas: Persona[];
  errors: string[];
  /** Set when the directory itself is absent — a different failure from an unparseable file. */
  missingDir?: string;
}

type PersonaFrontmatter = { name?: unknown; description?: unknown };

/**
 * One persona file, or the reason it is not one.
 *
 * `parseFrontmatter` is pi's own reader, imported rather than reimplemented so this and the
 * files adjust_agents.py writes cannot drift apart over a YAML detail. `name` and `description`
 * are required because a delegation names an agent and the model picks one from descriptions.
 */
export function parsePersona(text: string, filePath: string): Persona | { error: string } {
  const { frontmatter, body } = parseFrontmatter<PersonaFrontmatter>(text);
  if (typeof frontmatter.name !== "string" || !frontmatter.name.trim()) {
    return { error: `${basename(filePath)} has no \`name\` in its frontmatter` };
  }
  if (typeof frontmatter.description !== "string" || !frontmatter.description.trim()) {
    return { error: `${basename(filePath)} has no \`description\` in its frontmatter` };
  }
  return {
    name: frontmatter.name.trim(),
    description: frontmatter.description.trim(),
    systemPrompt: body,
    filePath,
  };
}

/** Read `<cwd>/.pi/agents/*.md`. `.md` is the suffix pi's own agent discovery matches. */
export function scanPersonas(cwd: string): PersonaScan {
  const dir = join(cwd, ...AGENTS_DIR);
  if (!existsSync(dir)) {
    return { personas: [], errors: [], missingDir: dir };
  }

  const scan: PersonaScan = { personas: [], errors: [] };
  let names: string[];
  try {
    names = readdirSync(dir);
  } catch (error) {
    return { personas: [], errors: [`${dir} could not be read (${String(error)})`] };
  }

  for (const name of names.sort()) {
    if (!name.endsWith(".md")) continue;
    const filePath = join(dir, name);
    let text: string;
    try {
      text = readFileSync(filePath, "utf-8");
    } catch (error) {
      scan.errors.push(`${name} could not be read (${String(error)})`);
      continue;
    }
    const parsed = parsePersona(text, filePath);
    if ("error" in parsed) {
      scan.errors.push(parsed.error);
      continue;
    }
    scan.personas.push(parsed);
  }
  return scan;
}

/** `name: description` for every persona, or "none" — what an unknown agent name is answered with. */
export function personaList(personas: Persona[]): string {
  if (personas.length === 0) return "none";
  return personas.map((p) => `${p.name}: ${p.description}`).join("\n");
}

/**
 * The argv for the delegated `pi -p` run.
 *
 * `--no-session` keeps a delegation out of the session store; `--exclude-tools` removes this
 * tool from the child so delegation cannot recurse; `--append-system-prompt` carries the
 * persona's body (pi appends it to the coding-assistant prompt rather than replacing it, so the
 * child keeps its tool guidance); `--` ends option parsing so a task starting with `-` is a task.
 */
export function delegationArgs(persona: Persona, task: string, model?: string): string[] {
  const args = ["-p", "--no-session", "--exclude-tools", TOOL_NAME];
  if (model) args.push("--model", model);
  if (persona.systemPrompt.trim()) args.push("--append-system-prompt", persona.systemPrompt);
  args.push("--", task);
  return args;
}

/**
 * How to re-invoke pi for the child process.
 *
 * Re-running this process's own script keeps the child on the same pi build; the `pi` on PATH is
 * the fallback when pi runs from a compiled binary whose script path is virtual.
 */
export function piInvocation(
  args: string[],
  proc: { argv: string[]; execPath: string } = process,
  exists: (path: string) => boolean = existsSync,
): { command: string; args: string[] } {
  const script = proc.argv[1];
  if (script && !script.startsWith("/$bunfs/root/") && exists(script)) {
    return { command: proc.execPath, args: [script, ...args] };
  }
  if (!/^(node|bun)(\.exe)?$/.test(basename(proc.execPath).toLowerCase())) {
    return { command: proc.execPath, args };
  }
  return { command: "pi", args };
}

/** Keep the last `MAX_OUTPUT_BYTES` of a child's output; the tail is where its answer is. */
export function capOutput(text: string, limit: number = MAX_OUTPUT_BYTES): string {
  if (text.length <= limit) return text;
  return `[...${text.length - limit} earlier characters dropped]\n${text.slice(-limit)}`;
}

export interface ChildResult {
  code: number | null;
  stdout: string;
  stderr: string;
  /** Set when the process could not run at all, as opposed to running and failing. */
  spawnError?: string;
}

function runPi(
  args: string[],
  cwd: string,
  signal: AbortSignal | undefined,
): Promise<ChildResult> {
  return new Promise((settle) => {
    const invocation = piInvocation(args);
    let child;
    try {
      child = spawn(invocation.command, invocation.args, {
        cwd,
        shell: false,
        signal,
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (error) {
      settle({ code: null, stdout: "", stderr: "", spawnError: String(error) });
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
      settle({ code: null, stdout, stderr, spawnError: String(error) });
    });
    child.on("close", (code) => {
      settle({ code, stdout, stderr });
    });
  });
}

const DelegateParams = Type.Object({
  agent: Type.String({ description: "Name of the ai-badger persona to delegate to" }),
  task: Type.String({ description: "The task, stated so the persona can act on it alone" }),
});

interface DelegateDetails {
  agent: string;
  exitCode: number | null;
  agentsDir: string;
  errors: string[];
}

/** The one content shape this tool returns. Written inline so the extension declares no
 * dependency beyond pi's own package and typebox, both of which pi aliases for extensions. */
function text(body: string) {
  return [{ type: "text" as const, text: body }];
}

export default function (pi: ExtensionAPI) {
  if (typeof pi?.registerTool !== "function") {
    console.error(
      "ai-badger: pi.registerTool is not a function — this pi build's extension API has moved; the delegation tool is not installed.",
    );
    return;
  }

  pi.registerTool({
    name: TOOL_NAME,
    label: "Delegate",
    description: [
      "Delegate a task to one of this project's ai-badger personas, each of which runs as a",
      `separate pi process with its own context. Personas live in ${AGENTS_DIR.join("/")}/*.md;`,
      "call this with an unknown agent name to get the list of available ones.",
    ].join(" "),
    parameters: DelegateParams,

    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const scan = scanPersonas(ctx.cwd);
      const agentsDir = scan.missingDir ?? join(ctx.cwd, ...AGENTS_DIR);

      if (scan.missingDir) {
        const message = `ai-badger: no personas — ${scan.missingDir} does not exist. Run welcome-ai-badger in this project to scaffold them.`;
        ctx.ui.notify(message, "warning");
        return {
          content: text(message),
          details: { agent: params.agent, exitCode: null, agentsDir, errors: [] },
        };
      }
      for (const error of scan.errors) {
        ctx.ui.notify(`ai-badger: persona skipped — ${error}`, "warning");
      }

      const persona = scan.personas.find((p) => p.name === params.agent);
      if (!persona) {
        const message = `ai-badger: no persona named "${params.agent}" in ${agentsDir}.\nAvailable:\n${personaList(scan.personas)}`;
        ctx.ui.notify(message, "warning");
        return {
          content: text(message),
          details: { agent: params.agent, exitCode: null, agentsDir, errors: scan.errors },
        };
      }

      const model = ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : undefined;
      // The execute signal is the turn's own; ctx.signal is the fallback for a build that only
      // populates the context. Either one aborting kills the child rather than orphaning it.
      const result = await runPi(
        delegationArgs(persona, params.task, model),
        ctx.cwd,
        signal ?? ctx.signal,
      );

      if (result.spawnError) {
        const message = `ai-badger: delegation to "${persona.name}" could not run (${result.spawnError})`;
        ctx.ui.notify(message, "warning");
        return {
          content: text(message),
          details: { agent: persona.name, exitCode: null, agentsDir, errors: scan.errors },
        };
      }
      if (result.code !== 0) {
        const message = `ai-badger: delegation to "${persona.name}" exited ${result.code}: ${capOutput(result.stderr).trim() || "(no stderr)"}`;
        ctx.ui.notify(message, "warning");
        return {
          content: text(message),
          details: { agent: persona.name, exitCode: result.code, agentsDir, errors: scan.errors },
        };
      }

      return {
        content: text(capOutput(result.stdout).trim() || "(the delegated run printed nothing)"),
        details: { agent: persona.name, exitCode: 0, agentsDir, errors: scan.errors },
      };
    },
  });
}
