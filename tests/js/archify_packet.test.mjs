// Pre-push `js`-lane backstop for the vendored archify packet.
//
// Compares this repo's delivered copy (`.ai-badger/skills/archify`) against the
// catalog source (`features/common/skills/archify`) file-by-file with the stdlib
// `crypto` module — no production helper — then runs `doctor` and `deliver` from
// the DELIVERED path and asserts the same 9-checks/showcase receipt shape the
// python integration test asserts from a scaffolded consumer. Any mismatch fails
// the run (exit non-zero via node:test); nothing here skips.
import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readdirSync, readFileSync, statSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");
const catalog = path.join(repo, "features", "common", "skills", "archify");
const delivered = path.join(repo, ".ai-badger", "skills", "archify");
const binary = path.join(delivered, "bin", "archify.mjs");
const example = path.join(delivered, "examples", "web-app.architecture.json");

// Receipt keys verified against the upstream tool before asserting: the receipt
// literal built by commandDeliver in bin/archify.mjs
// ({schemaVersion, ok, command, type, input, output, specification{sha256,bytes},
// artifact{sha256,bytes}, validation{checksPassed, checkCount,
// compositionProfile, compositionStatus, errors, warnings}}), the nine addCheck
// calls in scripts/check-render-output.mjs, and the handoff line
// "validation: 9/9 showcase, 0 errors, 0 warnings" in
// references/delivery-contract.md. Doctor exit codes verified in the same
// bin/archify.mjs: commandDoctor sets exitCode 0 or 1 only, never 2 (exit 2 is
// visual-check's Chrome-absent code).

function filesUnder(base) {
  const found = [];
  const visit = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        visit(full);
      } else if (entry.isFile()) {
        found.push(path.relative(base, full).split(path.sep).join("/"));
      }
    }
  };
  visit(base);
  return found.sort();
}

function sha256(file) {
  return createHash("sha256").update(readFileSync(file)).digest("hex");
}

test("delivered archify packet matches the catalog file-by-file", () => {
  assert.ok(existsSync(catalog), `catalog packet missing at ${catalog}`);
  assert.ok(existsSync(delivered), `delivered packet missing at ${delivered}`);
  const catalogFiles = filesUnder(catalog);
  const deliveredFiles = filesUnder(delivered);
  assert.ok(catalogFiles.length > 0, "the catalog archify tree holds no files");
  assert.ok(deliveredFiles.length > 0, "the delivered archify tree holds no files");
  assert.deepEqual(deliveredFiles, catalogFiles);
  const mismatched = catalogFiles.filter(
    (rel) => sha256(path.join(catalog, rel)) !== sha256(path.join(delivered, rel)),
  );
  assert.deepEqual(mismatched, []);
});

test("doctor exits 0 from the delivered copy", () => {
  assert.ok(existsSync(binary), `delivered binary missing at ${binary}`);
  // execFileSync throws on any non-zero exit, so reaching the next line proves rc == 0.
  execFileSync(process.execPath, [binary, "doctor"], { encoding: "utf8" });
});

test("deliver architecture --quality showcase reports the 9-check showcase receipt", () => {
  assert.ok(existsSync(binary), `delivered binary missing at ${binary}`);
  assert.ok(existsSync(example), `vendored example missing at ${example}`);
  const outHtml = path.join(mkdtempSync(path.join(os.tmpdir(), "aib-archify-")), "arch_out.html");
  const stdout = execFileSync(
    process.execPath,
    [binary, "deliver", "architecture", example, outHtml, "--quality", "showcase", "--json"],
    { encoding: "utf8" },
  );
  const receipt = JSON.parse(stdout);
  assert.equal(receipt.ok, true);
  assert.equal(receipt.validation.checkCount, 9);
  assert.equal(receipt.validation.checksPassed, 9);
  assert.equal(receipt.validation.compositionProfile, "showcase");
  assert.equal(receipt.validation.errors, 0);
  assert.equal(receipt.validation.warnings, 0);
  assert.ok(existsSync(outHtml), `deliver exited 0 but wrote no HTML at ${outHtml}`);
  assert.ok(statSync(outHtml).size > 0, `deliver wrote an empty HTML at ${outHtml}`);
});
