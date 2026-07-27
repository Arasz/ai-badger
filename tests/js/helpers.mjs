// Shared fixture helpers for the maintain-agent-instructions script tests.
// Both scripts are CLIs that read process.cwd() and exit — so they are run as real
// subprocesses against a throwaway project, which is also the contract CI depends on.
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const SCRIPTS = path.resolve(
  here, "..", "..", "features", "common", "skills", "maintain-agent-instructions", "scripts",
);

export const MODEL_DIR = ".ai-badger/agent-instructions";

export function makeProject(files = {}, model = undefined) {
  const root = mkdtempSync(path.join(tmpdir(), "aib-js-"));
  mkdirSync(path.join(root, MODEL_DIR), { recursive: true });
  writeFileSync(path.join(root, MODEL_DIR, "schema.json"), "{}\n");
  if (model !== undefined) {
    writeFileSync(path.join(root, MODEL_DIR, "model.json"), JSON.stringify(model, null, 2));
  }
  for (const [relative, contents] of Object.entries(files)) {
    const target = path.join(root, relative);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, contents);
  }
  return root;
}

// Returns {code, stdout, stderr} instead of throwing, so a failing gate is a value to assert on.
export function run(script, cwd) {
  try {
    const stdout = execFileSync(process.execPath, [path.join(SCRIPTS, script)], {
      cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
    });
    return { code: 0, stdout, stderr: "" };
  } catch (error) {
    return {
      code: error.status ?? 1,
      stdout: error.stdout ?? "",
      stderr: error.stderr ?? "",
    };
  }
}
