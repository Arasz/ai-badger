// The gate must FAIL on a broken project, not pass quietly (review F-47).
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeProject, run } from "./helpers.mjs";

const SCRIPT = "validate-agent-instructions.mjs";

const MINIMAL_MODEL = {
  version: 1,
  files: { claude: { path: "CLAUDE.md", required: true } },
};

test("a project matching its model passes", () => {
  const root = makeProject({ "CLAUDE.md": "# Project\n" }, MINIMAL_MODEL);

  const result = run(SCRIPT, root);

  assert.equal(result.code, 0);
  assert.match(result.stdout, /validation passed/);
});

test("a missing model.json fails", () => {
  const root = makeProject({ "CLAUDE.md": "# Project\n" });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /model\.json/);
});

test("an unsupported model version fails", () => {
  const root = makeProject({ "CLAUDE.md": "# Project\n" }, { ...MINIMAL_MODEL, version: 2 });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /Unsupported model version/);
});

test("a required file that does not exist fails", () => {
  const root = makeProject({}, MINIMAL_MODEL);

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /Required file missing/);
});

test("a missing required heading fails", () => {
  const root = makeProject({ "CLAUDE.md": "# Project\n\n## Commands\n" }, {
    ...MINIMAL_MODEL,
    validation: { requiredHeadings: { "CLAUDE.md": ["Non-negotiable invariants"] } },
  });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /missing heading "Non-negotiable invariants"/);
});

test("a present required heading passes", () => {
  const root = makeProject({ "CLAUDE.md": "# Project\n\n## Non-negotiable invariants\n" }, {
    ...MINIMAL_MODEL,
    validation: { requiredHeadings: { "CLAUDE.md": ["Non-negotiable invariants"] } },
  });

  assert.equal(run(SCRIPT, root).code, 0);
});

test("a heading missing its agent-section metadata fails", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n\n## Commands\n\ntext\n" }, {
    ...MINIMAL_MODEL,
    validation: {
      requiredHeadings: { "CLAUDE.md": [{ text: "Commands", metadata: { owner: "badger" } }] },
    },
  });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /agent-section metadata/);
});

test("a heading carrying the required metadata passes", () => {
  const body = '# P\n\n## Commands\n<!-- agent-section: {"owner": "badger"} -->\n\ntext\n';
  const root = makeProject({ "CLAUDE.md": body }, {
    ...MINIMAL_MODEL,
    validation: {
      requiredHeadings: { "CLAUDE.md": [{ text: "Commands", metadata: { owner: "badger" } }] },
    },
  });

  assert.equal(run(SCRIPT, root).code, 0);
});

test("a forbidden pattern present in the file fails", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n\nrun pip install -g everything\n" }, {
    ...MINIMAL_MODEL,
    validation: { forbiddenPatterns: { "CLAUDE.md": ["pip install -g"] } },
  });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /forbidden pattern/);
});

test("a required pattern absent from the file fails", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n" }, {
    ...MINIMAL_MODEL,
    validation: { requiredPatterns: { "CLAUDE.md": ["TDD is mandatory"] } },
  });

  assert.equal(run(SCRIPT, root).code, 1);
});

test("an instruction set missing its frontmatter description fails", () => {
  const root = makeProject({
    "CLAUDE.md": "# P\n",
    "instructions/python.md": "---\napplyTo: '**/*.py'\n---\n\n# Python\n",
  }, {
    ...MINIMAL_MODEL,
    instructionSets: {
      python: {
        path: "instructions/python.md",
        frontmatter: { descriptionRequired: true, applyToRequired: true },
      },
    },
  });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /missing description/);
});

test("an instruction set missing a required topic fails", () => {
  const root = makeProject({
    "CLAUDE.md": "# P\n",
    "instructions/python.md": "---\ndescription: 'x'\napplyTo: '**/*.py'\n---\n\n# Python\n",
  }, {
    ...MINIMAL_MODEL,
    instructionSets: {
      python: {
        path: "instructions/python.md",
        requiredTopics: [{ id: "typing", patterns: ["type hints"] }],
      },
    },
  });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /missing required topic typing/);
});

test("an over-long file warns without failing", () => {
  const root = makeProject({ "CLAUDE.md": "x\n".repeat(50) }, {
    ...MINIMAL_MODEL,
    files: { claude: { path: "CLAUDE.md", required: true, warnAboveLines: 10 } },
  });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 0);
  assert.match(result.stdout, /warning threshold/);
});

test("a directory missing an expected file fails", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n", "instructions/keep.md": "x\n" }, {
    ...MINIMAL_MODEL,
    directories: {
      instructions: { path: "instructions", required: true, allowedFiles: ["python.md"] },
    },
  });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /missing expected file python\.md/);
});


test("an oversized pattern is reported, not thrown as a stack trace", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n" }, {
    ...MINIMAL_MODEL,
    validation: { requiredPatterns: { "CLAUDE.md": ["(a+)+".repeat(200)] } },
  });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /pattern too long/i);
  assert.doesNotMatch(result.stderr, /at Object\.|at Module\./);
});


// Seven characters, so the length cap never sees it, and it backtracks catastrophically
// against a non-matching input: measured as a hang, not a slow run (review B16).
test("a quantified group is reported, not run", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n" }, {
    ...MINIMAL_MODEL,
    validation: { requiredPatterns: { "CLAUDE.md": ["^(a+)+$"] } },
  });

  const result = run(SCRIPT, root);

  assert.equal(result.code, 1);
  assert.match(result.stderr, /nested quantifier/i);
  assert.doesNotMatch(result.stderr, /at Object\.|at Module\./);
});

test("a forbidden pattern with a quantified group is reported too", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n" }, {
    ...MINIMAL_MODEL,
    validation: { forbiddenPatterns: { "CLAUDE.md": ["(ab|a)+c"] } },
  });

  assert.match(run(SCRIPT, root).stderr, /nested quantifier/i);
});

test("an unquantified group is still a legal pattern", () => {
  const root = makeProject({ "CLAUDE.md": "# P\n\nTDD is mandatory.\n" }, {
    ...MINIMAL_MODEL,
    validation: { requiredPatterns: { "CLAUDE.md": ["(TDD|BDD) is mandatory"] } },
  });

  assert.equal(run(SCRIPT, root).code, 0);
});
