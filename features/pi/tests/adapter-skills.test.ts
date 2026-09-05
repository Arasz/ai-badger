/**
 * The adapter's `resources_discover` skills contribution, driven the way pi drives it:
 * the handler must contribute the canonical `.ai-badger/skills` namespaces without the
 * `learned/` subtree. `learned/` is ai-badger's separate per-session namespace that
 * reuses canonical skill names — contributing the tree root flattens both namespaces
 * into pi's flat name pool and warns a collision per duplicated name (35 in ai-raccoon).
 */

import { describe, expect, test } from "bun:test";
import { existsSync, mkdirSync, rmSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import adapter from "../adjustments/adapter/index.ts";

type Handler = (event: unknown, ctx: unknown) => unknown;

async function loadHandlers(): Promise<Map<string, Handler>> {
  const on = new Map<string, Handler>();
  await adapter({
    on: (event: string, handler: Handler) => on.set(event, handler),
  } as never);
  return on;
}

function skill(dir: string, name: string): void {
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "SKILL.md"), `---\nname: ${name}\ndescription: x\n---\n`);
}

describe("resources_discover skills contribution", () => {
  test("contributes canonical skills but never the learned/ subtree", async () => {
    const on = await loadHandlers();
    const discover = on.get("resources_discover")!;
    expect(typeof discover).toBe("function");

    const cwd = mkdtempSync(join(tmpdir(), "aib-skills-"));
    try {
      const skills = join(cwd, ".ai-badger", "skills");
      skill(join(skills, "code-review"), "code-review");
      skill(join(skills, "dotnet-workload"), "dotnet-workload");
      skill(join(skills, "dotnet-workload", "references", "dotnet-bdd-testing"), "dotnet-bdd-testing");
      skill(join(skills, "learned", "uncategorized", "code-review"), "code-review");
      skill(join(skills, "learned", "software-development", "red-proof"), "red-proof");

      const result = discover({ cwd }, {}) as { skillPaths: string[] };
      const paths: string[] = result.skillPaths ?? [];

      // canonical entries are contributed (directly or via a recursed container)
      expect(paths).toContain(join(skills, "code-review"));
      expect(paths).toContain(join(skills, "dotnet-workload"));
      // the tree root itself must not be contributed (it recurses into learned/)
      expect(paths).not.toContain(skills);
      // nothing under learned/ may be contributed, explicitly or via the root
      expect(paths.filter((p) => p.split("/").includes("learned"))).toEqual([]);
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  });

  test("absent skills dir contributes no paths and never throws", async () => {
    const on = await loadHandlers();
    const discover = on.get("resources_discover")!;
    const cwd = mkdtempSync(join(tmpdir(), "aib-skills-empty-"));
    try {
      expect(existsSync(join(cwd, ".ai-badger", "skills"))).toBe(false);
      const result = discover({ cwd }, {}) as { skillPaths: string[] };
      expect(result).toEqual({ skillPaths: [] });
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  });
});
