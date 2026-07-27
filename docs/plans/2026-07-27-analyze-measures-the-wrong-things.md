# Plan — `call-behaviorist analyze` is measuring the wrong things

**Status:** planned, not started. Written 2026-07-27 17:40 CEST to be picked up by a fresh
session. **Assume the reader has no context.** Session state is in
[`2026-07-27-session-checkpoint-3.md`](2026-07-27-session-checkpoint-3.md) — read that first for
what else is in flight.

**Source:** a health report produced by running `analyze` against a real consuming project
(`job-search-ai-assistant`, framework 0.33.0). Its verdict: *"the report has no evidence to
offer, and the analyzer is measuring the wrong things. Nothing here indicates a broken hook — it
indicates that nobody was looking, plus two defects in the observability tooling itself."*
A third defect was found while reproducing it.

**Nothing here is a hypothesis.** Every claim below was reproduced against this repo before the
plan was written; each carries the command that shows it.

---

## Why this matters more than its size suggests

`call-behaviorist` exists to answer one question: *did that hook actually run?* It was built
because ai-badger is silent about its own machinery, and because three separate defects this
session — plugin hooks not loading, the dead extension mechanism, `task` pointing at a
non-existent path — all survived green CI by being invisible.

A health tool that reports a verdict it has no evidence for, and that cannot see two of the five
hooks it is auditing, is worse than no tool: it converts "we don't know" into "we checked."
The repo has twice decided that a gate which cries wolf is worse than no gate
([ADR-0006](../adr/0006-one-skill-extension-mechanism.md);
[`0.19.0`](../changelog/0.19.0-destructive-write-guards.md)). Same rule applies here, to
ourselves.

---

## Defect A — it audits the wrong file

`_wired_hooks()` (`features/common/skills/call-behaviorist/scripts/behaviorist.py:143`) reads:

```python
hooks_file = Path(project) / ".ai-badger" / "hooks" / "hooks.json"
```

That file records what ai-badger **intended** to wire. Hooks actually run from what is
**registered** in `.claude/settings.json`. Those are different sets, because other adjustments,
other skills and the user's own configuration all write there.

**Reproduce:**

```bash
.venv/bin/python -c "
import json
h=json.load(open('.ai-badger/hooks/hooks.json'))
print('intended :', sum(len(x.get(\"hooks\",[])) for e in h.get('hooks',{}).values() for x in e))
s=json.load(open('.claude/settings.json'))
print('registered:', sum(len(x.get(\"hooks\",[])) for e in s.get('hooks',{}).values() for x in e))
"
# intended : 2      registered: 4
```

In the reporting project it was **2 of 5**. `task/scripts/drift_notice_hook.py` and
`task/scripts/stop_hook.py` are wired and **invisible to the analyzer** — if either stopped
firing, the report would not say so.

This is the same failure class the tool exists to catch, in the tool itself.

### What to do

Enumerate from the **registration**, not the declaration. `.claude/settings.json` is the source
of truth for what Claude Code will run.

Decide and state explicitly:

- **Whose hooks count?** `settings.json` also holds third-party hooks (this repo has
  `code-review-graph` entries; the reporting project had more). They are not ai-badger's to
  audit, but "unexpected component" already exists as a low-severity finding for exactly this.
  Prefer classifying over filtering — a hook ai-badger did not wire is *information*, not noise.
- **Which file, in which shape?** A Hermes-only project has no `.claude/settings.json`. Do not
  regress Hermes and Copilot by keying the analyzer to one agent. `.ai-badger/hooks/hooks.json`
  may still be a legitimate *secondary* source; the bug is using it as the only one.

---

## Defect B — it keys on basename, so distinct hooks conflate

Same function, the line after:

```python
match = re.search(r'([^\s"\']+/)?([A-Za-z0-9_\-]+)\.py', hook.get("command", ""))
if match:
    found[match.group(2)] = (match.group(1) or "") + match.group(2) + ".py"
```

`found` is keyed by `match.group(2)` — the bare stem. Two different `user_prompt_hook.py` exist:

| Path | Instrumented? |
|---|---|
| `.ai-badger/skills/task/scripts/user_prompt_hook.py` | no |
| `.ai-badger/skills/prompt-markers/scripts/user_prompt_hook.py` | **yes** |

They collapse into one component and are reported as a single `not_instrumented` finding.

**This does not merely lose precision — it suppresses a true positive.** If the prompt-markers
hook stopped firing, `never_observed` would never trigger, because the sibling's lack of
instrumentation explains the silence away. A defect that makes the detector quieter is worse than
one that makes it noisier.

### What to do

Key by **path** (repo-relative), not basename. Note that `is_instrumented()` already takes a
path, so the data is there — only the key is wrong.

Watch the interaction with `_matches()`, which exists to reconcile *observed* names
(phase-qualified, e.g. `ai_badger_hooks/session_start`) against *wired* names (bare stems). That
reconciliation was itself a bug fix in 0.31.0; changing the key on one side without the other
will re-break it. **Read `docs/changelog/0.31.0-a-health-report-from-evidence.md` before
touching `_matches`.**

---

## Defect C — its own bookkeeping counts as evidence, so `unknown` is unreachable

`call-behaviorist` records its own lifecycle events — `enabled`, `disabled`, `cleared` — with no
project. `_read_records()` deliberately admits project-less records into every project's
analysis, so that user-scope hooks stay visible:

```python
if project and rec.get(dl.KEY_PROJECT) not in (None, project):
    continue
```

But `health` is gated on the record count:

```python
if not records:
    health = "unknown"
```

So once anyone has ever run `clear`, `records` is never empty and **`unknown` becomes
unreachable**. The tool also counts itself as an `unexpected_component`.

`unknown` is documented in `SKILL.md` as meaning *"nobody looked"*, with an explicit instruction
to say so plainly rather than imply health. Right now the code cannot express it.

**Reproduce** — one `cleared` record, nothing else:

```
health: degraded   records: 1
findings: [('never_observed', 'session_start_hook', 'high'),
           ('unexpected_component', 'call-behaviorist', 'low')]
```

The reporting project saw `warn` rather than `degraded` — the same defect down a different
branch (their findings were all low-severity; the repro above hits the high-severity path). Both
are verdicts resting on no evidence.

### What to do

Separate **evidence** from **bookkeeping**. Health is computed from evidence only; `unknown`
means no evidence, not no lines. Never report the tool itself as an unexpected component.

The subtle part: **`never_observed` is vacuous when nothing was observed at all.** "This hook
produced no record" is only meaningful if the log shows the system was being observed while the
hook should have fired. With zero evidence, everything is trivially unobserved — which is how one
bookkeeping line produced a high-severity alarm.

---

## Already done — do not redo

Branch **`fix/behaviorist-evidence-vs-bookkeeping`** (pushed, **not** merged) holds five tests
for defect C, four RED and one guard:

| Test | Expected |
|---|---|
| `test_only_bookkeeping_records_still_reports_unknown` | RED |
| `test_no_high_severity_finding_is_raised_without_evidence` | RED |
| `test_the_tool_is_not_reported_as_an_unexpected_component` | RED |
| `test_the_window_counts_evidence_not_bookkeeping` | RED |
| `test_real_evidence_still_produces_a_real_finding` | **green before and after** |

That last one is the important one: it asserts genuine silence is still reported. **The fix must
mute the false alarms without muting the real signal**, and it is the only thing standing between
"fix the false positives" and "make the tool always say `ok`."

No production code has been changed. Defects A and B have no tests yet.

---

## Order of work

1. **Defect C first.** Its tests exist and are red; it is self-contained; and until `unknown`
   works, A and B cannot be evaluated honestly — every run reports a verdict regardless.
2. **Defect B second.** Small, and it changes the shape of the data A depends on.
3. **Defect A last**, because it is the one with a real design decision (which file, which
   agent, whose hooks) and it benefits from B's path-keyed data already being in place.

TDD throughout — this repo requires a failing behaviour-focused test before any production
change, and every defect above exists because something was assumed rather than asserted.

**End-to-end acceptance, worth writing before you start:** a project wiring five hooks in
`.claude/settings.json`, two of them instrumented, with an empty audit log, reports
`health: unknown` and names all five as expected components. Today it reports a verdict, sees
two, and conflates two of those.

---

## Files, and who else may be in them

Yours: `features/common/skills/call-behaviorist/scripts/behaviorist.py`,
`features/common/skills/call-behaviorist/SKILL.md`, `tests/test_behaviorist_analyze.py`.

- **Regenerate mirrors, never hand-edit them.** The catalog copy is under `features/`; generated
  copies live at `skills/<name>/...` (repo root) and `.ai-badger/skills/<name>/...`. Use
  `.venv/bin/python scripts/sync_plugin_skills.py`. Note the plugin mirror moved from
  `.claude/skills/` to `skills/` on 2026-07-27 — see
  [ADR-0008](../adr/0008-plugin-skills-live-at-the-plugin-skill-path.md).
- `debug_log.py` is **vendored byte-identically** into
  `features/common/skills/call-behaviorist/scripts/` from `features/common/hooks/`, enforced by a
  test. If defect C needs a change there, change the canonical copy and re-vendor — do not edit
  one side.
- Check the checkpoint for live agents before starting. At time of writing, work is in flight on
  `drift.py`, `refresh.py`, `scaffold.py`, `badger_lib.py` and every `_bootstrap_lib()` preamble.
  None of those are needed here.

## Gates and release rules

All must pass, using `.venv/bin/python` (`python3` on PATH is 3.14 and has no pytest):

```
pytest -q · pylint scripts features · validate.py --all · index_build.py --check
docs_guard.py · deps_guard.py · sync_plugin_skills.py --check · node --test "tests/js/*.test.mjs"
```

Per [`CLAUDE.md`](../../CLAUDE.md): bump `VERSION` and add `docs/changelog/{version}-{slug}.md`.
**But check the checkpoint first** — 20 commits were already unreleased when this was written, so
this work probably folds into that release rather than getting its own. `release_guard.py`
decides whether a bump is required; do not guess.

## Also worth fixing, or at least recording

The user-scope audit log is dominated by **ai-badger's own test suite** — of 141 records in the
reporting run, most `project` values were `pytest-of-arasz/pytest-NNN/...` temp directories. Real
hook activity and test activity share one file, so every per-project analysis reads through that
noise. Not part of the three defects, and not obviously a bug, but it makes the log far less
useful than its size suggests. Options: point the tests at an isolated `DEBUG_DIR`, or teach
`analyze` to recognise and exclude ephemeral project paths. Decide deliberately rather than
letting it stand by default.
