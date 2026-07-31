import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = join(import.meta.dirname, "../..", "features/common/skills");
const form = readFileSync(join(root, "create-refinement-document/references/form-template.html"), "utf8");
const skill = readFileSync(join(root, "create-refinement-document/SKILL.md"), "utf8");
const result = readFileSync(join(root, "create-refinement-document/references/result-template.md"), "utf8");

 test("the agent protocol fills every per-review CONFIG field", () => {
  assert.match(skill, /CONFIG\.outName/);
  assert.match(skill, /CONFIG\.expectedDir/);
  assert.match(skill, /CONFIG\.storageKey/);
  assert.doesNotMatch(skill, /Fill the DECISIONS array and OUT_NAME/);
  assert.doesNotMatch(skill, /EXPECTED_PATH/);
});

test("claims are rendered as text rather than interpreted HTML", () => {
  assert.match(form, /claimSpan\.textContent\s*=\s*d\.claim \|\| ""/);
  assert.doesNotMatch(form, /d-claim[\s\S]{0,120}\+\s*\(d\.claim \|\| ""\)/);
});

test("note output cannot be mistaken for the item separator", () => {
  assert.match(form, /function markdownNote\(note\)/);
  assert.match(form, /markdownNote\(e\.note\)/);
  assert.match(result, /blockquoted/);
  assert.match(result, /Strip the `> ` prefix/);
});

test("both new skills expose authoring metadata and verification", () => {
  for (const name of ["create-refinement-document", "differential-feature-refactor"]) {
    const content = readFileSync(join(root, name, "SKILL.md"), "utf8");
    assert.match(content, /^version:\s*1\.0\.0/m);
    assert.match(content, /^metadata:/m);
    assert.match(content, /^## Verification Checklist/m);
  }
});
