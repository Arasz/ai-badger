/**
 * Unit tests for the ai-badger subagent extension's pure logic: persona parsing, the
 * directory scan (including the two ways it can find nothing), the child-process argument
 * construction, and the pi re-invocation ladder.
 */

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  AGENTS_DIR,
  TOOL_NAME,
  capOutput,
  delegationArgs,
  personaList,
  parsePersona,
  piInvocation,
  scanPersonas,
  type Persona,
} from "../subagent/index.ts";

/** Exactly what adjust_agents.py writes: two frontmatter keys, then the managed header. */
const SCAFFOLDED = `---
name: architect
description: >
  Architecture and decomposition specialist. Read-only.
---

<!-- Managed by ai-badger. Source of truth: .ai-badger/agents/architect.md. Do not edit this copy by hand; edit the source and re-run welcome-ai-badger. -->

# Architect

Produce a blueprint, never an edit.
`;

function persona(overrides: Partial<Persona> = {}): Persona {
  return {
    name: "architect",
    description: "Architecture specialist",
    systemPrompt: "# Architect\n",
    filePath: "/tmp/architect.md",
    ...overrides,
  };
}

describe("parsePersona", () => {
  test("reads name, description and body from a scaffolded persona file", () => {
    const parsed = parsePersona(SCAFFOLDED, "/p/.pi/agents/architect.md");

    expect(parsed).not.toHaveProperty("error");
    const ok = parsed as Persona;
    expect(ok.name).toBe("architect");
    expect(ok.description).toBe("Architecture and decomposition specialist. Read-only.");
    expect(ok.systemPrompt).toContain("Produce a blueprint, never an edit.");
    expect(ok.filePath).toBe("/p/.pi/agents/architect.md");
  });

  test("a file with no frontmatter is an error naming the file, not a nameless persona", () => {
    const parsed = parsePersona("# Just a heading\n", "/p/.pi/agents/notes.md");

    expect(parsed).toEqual({ error: "notes.md has no `name` in its frontmatter" });
  });

  test("a persona with no description is an error — the model picks agents by description", () => {
    const parsed = parsePersona("---\nname: architect\n---\n\nbody\n", "/p/.pi/agents/a.md");

    expect(parsed).toEqual({ error: "a.md has no `description` in its frontmatter" });
  });
});

describe("scanPersonas", () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "aib-subagent-"));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  test("a missing agents directory is reported as missingDir, never as an empty list", () => {
    const scan = scanPersonas(dir);

    expect(scan.missingDir).toBe(join(dir, ...AGENTS_DIR));
    expect(scan.personas).toEqual([]);
  });

  test("reads every .md persona and skips other files", () => {
    const agents = join(dir, ...AGENTS_DIR);
    mkdirSync(agents, { recursive: true });
    writeFileSync(join(agents, "architect.md"), SCAFFOLDED);
    writeFileSync(join(agents, "qa.md"), "---\nname: qa\ndescription: Test authority\n---\n\nx\n");
    writeFileSync(join(agents, "README.txt"), "not a persona");

    const scan = scanPersonas(dir);

    expect(scan.missingDir).toBeUndefined();
    expect(scan.personas.map((p) => p.name)).toEqual(["architect", "qa"]);
    expect(scan.errors).toEqual([]);
  });

  test("one unparseable persona is reported and the rest still load", () => {
    const agents = join(dir, ...AGENTS_DIR);
    mkdirSync(agents, { recursive: true });
    writeFileSync(join(agents, "architect.md"), SCAFFOLDED);
    writeFileSync(join(agents, "broken.md"), "no frontmatter here\\n");

    const scan = scanPersonas(dir);

    expect(scan.personas.map((p) => p.name)).toEqual(["architect"]);
    expect(scan.errors).toEqual(["broken.md has no `name` in its frontmatter"]);
  });

  test("a frontmatter that is invalid YAML is reported, and the rest still load", () => {
    const agents = join(dir, ...AGENTS_DIR);
    mkdirSync(agents, { recursive: true });
    writeFileSync(join(agents, "architect.md"), SCAFFOLDED);
    writeFileSync(join(agents, "broken.md"), "---\ndescription: [unclosed\n---\n\nbody\n");

    const scan = scanPersonas(dir);

    expect(scan.personas.map((p) => p.name)).toEqual(["architect"]);
    expect(scan.errors).toHaveLength(1);
    expect(scan.errors[0]).toContain("broken.md could not be parsed");
  });

  test("two files claiming the same name keep the first and name the shadowed one", () => {
    const agents = join(dir, ...AGENTS_DIR);
    mkdirSync(agents, { recursive: true });
    writeFileSync(join(agents, "a-architect.md"), SCAFFOLDED);
    writeFileSync(
      join(agents, "b-architect.md"),
      "---\nname: architect\ndescription: A shadow\n---\n\nx\n",
    );

    const scan = scanPersonas(dir);

    expect(scan.personas.map((p) => p.name)).toEqual(["architect"]);
    expect(scan.personas[0].filePath).toContain("a-architect.md");
    expect(scan.duplicates).toHaveLength(1);
    expect(scan.duplicates?.[0]).toContain("a-architect.md");
    expect(scan.duplicates?.[0]).toContain("b-architect.md");
  });
});

describe("delegationArgs", () => {
  test("runs headless, keeps no session, and excludes itself so delegation cannot recurse", () => {
    const args = delegationArgs(persona(), "Draft the plan");

    expect(args).toEqual([
      "-p",
      "--no-session",
      "--exclude-tools",
      TOOL_NAME,
      "--append-system-prompt",
      "# Architect\n",
      "--",
      "Draft the plan",
    ]);
  });

  test("the model is passed only when the session has one", () => {
    expect(delegationArgs(persona(), "t", "openrouter/moonshotai/kimi-k2.6")).toContain("--model");
    expect(delegationArgs(persona(), "t")).not.toContain("--model");
  });

  test("an empty persona body sends no --append-system-prompt", () => {
    const args = delegationArgs(persona({ systemPrompt: "  \n" }), "t");

    expect(args).not.toContain("--append-system-prompt");
    expect(args.slice(-2)).toEqual(["--", "t"]);
  });

  test("the task is the last argument, behind `--`, so a leading dash stays a task", () => {
    const args = delegationArgs(persona(), "--version");

    expect(args.slice(-2)).toEqual(["--", "--version"]);
  });
});

describe("piInvocation", () => {
  test("re-runs this process's own script, keeping the child on the same pi build", () => {
    const out = piInvocation(["-p"], { argv: ["node", "/opt/pi/cli.js"], execPath: "/bin/node" },
      () => true);

    expect(out).toEqual({ command: "/bin/node", args: ["/opt/pi/cli.js", "-p"] });
  });

  test("falls back to `pi` on PATH when the script path is bun's virtual filesystem", () => {
    const out = piInvocation(["-p"], { argv: ["bun", "/$bunfs/root/pi"], execPath: "/bin/bun" },
      () => true);

    expect(out).toEqual({ command: "pi", args: ["-p"] });
  });

  test("a non-generic executable is itself the pi binary", () => {
    const out = piInvocation(["-p"], { argv: ["/usr/local/bin/pi"], execPath: "/usr/local/bin/pi" },
      () => false);

    expect(out).toEqual({ command: "/usr/local/bin/pi", args: ["-p"] });
  });
});

describe("output handling", () => {
  test("capOutput keeps the tail, where a delegated run's answer is", () => {
    const capped = capOutput("abcdefghij", 4);

    expect(capped).toBe("[...6 earlier characters dropped]\nghij");
  });

  test("capOutput's budget is counted in characters, matching how it slices", () => {
    expect(capOutput("aé".repeat(3), 4)).toBe(
      "[...2 earlier characters dropped]\naéaé",
    );
  });

  test("capOutput leaves output under the limit alone", () => {
    expect(capOutput("short", 100)).toBe("short");
  });

  test("personaList names every persona, and says so when there are none", () => {
    expect(personaList([persona()])).toBe("architect: Architecture specialist");
    expect(personaList([])).toBe("none");
  });
});
