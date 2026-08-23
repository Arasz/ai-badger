// The drift gate must FAIL when an invariant stops being mentioned (review F-47).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { makeProject, run } from "./helpers.mjs";

const SCRIPT = "check-agent-drift.mjs";

function modelWith(rules) {
  return { version: 1, sharedPolicy: { nonNegotiableInvariants: rules } };
}

const TDD_RULE = {
  id: "tdd-mandatory",
  summary: "TDD is mandatory",
  patterns: ["TDD is mandatory"],
  mustAppearIn: ["CLAUDE.md"],
};

test("the repo model encodes the prompt-policy rule set for short-horizon work", () => {
  const modelPath = new URL("../../.ai-badger/agent-instructions/model.json", import.meta.url);
  const model = JSON.parse(readFileSync(modelPath, "utf8"));
  const invariants = model.sharedPolicy?.nonNegotiableInvariants ?? [];
  const expected = [
    "one-turn specification",
    "consolidated restart",
    "grounded feedback",
    "tool schema and success criteria outrank persona prose",
    "critical instruction placement",
    "reasoning scaffolding minimization",
    "final output schema separation",
    "positive constraints and validation",
    "few-shot only for format",
  ];

  const summaries = invariants.map((item) => item.summary ?? "");
  for (const expectedRule of expected) {
    assert.ok(
      summaries.some((summary) => new RegExp(expectedRule, "i").test(summary)),
      `repo model should encode the prompt rule: ${expectedRule}`,
    );
  }
});

test("the generated instruction files mention each prompt-rule in the repo policy", () => {
  const expected = [
    "one-turn specification",
    "consolidated restart",
    "grounded feedback",
    "tool schema and success criteria outrank persona prose",
    "critical instruction placement",
    "reasoning scaffolding minimization",
    "final output schema separation",
    "positive constraints and validation",
    "few-shot only for format",
  ];

  for (const file of ["CLAUDE.md", "copilot-instructions.md"]) {
    const path = new URL(`../../.ai-badger/${file}`, import.meta.url);
    const text = readFileSync(path, "utf8");
    for (const expectedRule of expected) {
      assert.match(text, new RegExp(expectedRule, "i"),
        `expected ${file} to mention the prompt rule: ${expectedRule}`);
    }
  }
});

test("an invariant present in every target file passes", () => {
  const root = makeProject(
    { "CLAUDE.md": "# P\n\nTDD is mandatory here.\n" }, modelWith([TDD_RULE]),
  );

  const result = run(SCRIPT, root);

  assert.equal(result.code, 0);
  assert.match(result.stdout, /drift check passed/);
});

test("an invariant missing from a target file fails and names it", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n\nNothing about testing.\n" },
    modelWith([TDD_RULE]));

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /CLAUDE\.md does not mention invariant tdd-mandatory/);
  assert.match(result.stderr, /TDD is mandatory/);
});

test("a rule pointing at a file that does not exist fails", () => {
  const root = makeProject({}, modelWith([TDD_RULE]));

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /expects missing file CLAUDE\.md/);
});

test("a missing model.json fails", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n" });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /model\.json/);
});

test("an unparseable model.json fails instead of passing empty", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n" }, {});
  writeFileSync(`${root}/.ai-badger/agent-instructions/model.json`, "{ not json");

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /Failed to parse/);
});

test("review categories are checked the same way as invariants", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n" }, {
    version: 1,
    sharedPolicy: {
      reviewCategories: [{
        id: "security",
        summary: "Security review",
        patterns: ["security"],
        mustAppearIn: ["CLAUDE.md"],
      }],
    },
  });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /does not mention review category security/);
});

test("patterns match case-insensitively and across lines", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n\ntdd IS\nMANDATORY\n" }, modelWith([{
    ...TDD_RULE, patterns: ["tdd is\\s+mandatory"],
  }]));

  assert.equal(run(SCRIPT, root).code, 0);
});


test("an oversized pattern is rejected rather than compiled", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n" }, modelWith([{
    ...TDD_RULE, patterns: ["(a+)+".repeat(200)],
  }]));

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /pattern too long/i);
});

test("an oversized file is not scanned", () => {
  const root = makeProject({ "CLAUDE.md": "x".repeat(2_000_000) }, modelWith([TDD_RULE]));

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /too large/i);
});


// Seven characters, so the length cap never sees it, and it backtracks catastrophically
// against a non-matching input: measured as a hang, not a slow run (review B16).
test("a quantified group is rejected rather than compiled", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n" }, modelWith([{
    ...TDD_RULE, patterns: ["^(a+)+$"],
  }]));

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /nested quantifier/i);
  assert.match(result.stderr, /\^\(a\+\)\+\$/);
});

test("an alternation inside a quantified group is rejected too", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n" }, modelWith([{
    ...TDD_RULE, patterns: ["^(a|aa)+$"],
  }]));

  assert.match(run(SCRIPT, root).stderr, /nested quantifier/i);
});

test("an ordinary quantifier outside a group still compiles and matches", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n\nTDD is    mandatory.\n" }, modelWith([{
    ...TDD_RULE, patterns: ["TDD is\\s+mandatory"],
  }]));

  assert.equal(run(SCRIPT, root).code, 0);
});

test("a group that is not quantified still compiles", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n\nTDD is mandatory.\n" }, modelWith([{
    ...TDD_RULE, patterns: ["(TDD|BDD) is mandatory"],
  }]));

  assert.equal(run(SCRIPT, root).code, 0);
});
