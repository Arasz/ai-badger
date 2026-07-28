# Wave 6 — `Scaffolder`'s mixins become composed collaborators

**Branch:** `refactor/scaffold-collaborators` · **Executor:** one agent, worktree-isolated
**Parallel-safe with:** [Wave 16 phase 1](2026-07-28-wave-16-scripts-directory.md) — zero file overlap.

This plan is written to be executed without re-deriving any decision. Everything marked
**DECIDED** is settled; do not revisit it. If you hit something this plan does not cover, stop
and ask rather than inventing an answer.

---

## 1. What is wrong

`Scaffolder` inherits from six mixins that are not independently constructible. They communicate
through `self`, so any of them can reach any attribute or method of any other, and none can be
tested or reasoned about alone.

```python
class Scaffolder(
    McpToolsMixin, HookWiringMixin, StatusLineWiringMixin,
    TemplateRenderingMixin, AgentFilesMixin, ExtensionsMixin,
):
```

**Three facts in the older plan are now out of date. Use these instead:**

| Older plan said | Actual, verified 2026-07-28 |
|---|---|
| five mixins | **six** — `StatusLineWiringMixin` landed later |
| 77 `Scaffolder(...)` constructions in 11 test files | **103 constructions across 23 test files** |
| — | two shared attributes are new: `excluded` (0.36.0) and `carried_body` |

## 2. The actual coupling — measured, not guessed

Every `self.X` each mixin touches (data attributes only; methods are in §3):

| Attribute | McpTools | HookWiring | StatusLine | TemplateRendering | AgentFiles | Extensions |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| `config` | ● | ● | ● | ● | ● | ● |
| `notes` | ● | ● | ● | ● | ● | ● |
| `target` | ● | ● | ● | ● | ● | |
| `root` | ● | ● | | ● | ● | |
| `aib` | | ● | ● | | ● | |
| `stacks` | ● | | | | | |
| `index` | | | | ● | | |
| `overwrite` | | | | ● | | |
| `excluded` | | ● | | | | |
| `carried_body` | | | | ● | ● | |
| `_merged_external_tools` | ● | | | ● | | |
| `_external_tools_merged` | ● | | | | | |

That is a **context object**, not a god object — which is what makes this refactor tractable.

## 3. The three cross-mixin edges — the part that needs a decision

These are method calls *between* mixins, and they are why "just split the files" does not work.
**All three resolutions are DECIDED:**

| Edge | Where it is now | **DECIDED resolution** |
|---|---|---|
| `TemplateRendering` reads `self._merged_external_tools` (owned by `McpTools`) | `template_rendering.py` → `mcp_tools.py` | **Move the cache onto the context.** `McpTools` fills `ctx.merged_external_tools`; `TemplateRendering` reads it. Collaborators never reference each other for this. |
| `AgentFiles` calls `self._render_template_file`, `self._compute_doc_slots`, `self.carried_body` | `agent_files.py` → `template_rendering.py` | **An explicit collaborator argument.** `AgentFiles.__init__(ctx, template_rendering)`. This dependency is real and should be visible, not hidden in `self`. |
| `AgentFiles` calls `self.record_template` | `agent_files.py` → `scaffold.py` | **Move `record_template` onto the context.** It is manifest bookkeeping — shared state, not `Scaffolder` behaviour. |

**Resulting dependency graph** (this is the extraction order — leaves first):

```
Extensions ─┐
StatusLine ─┤ (leaves: context only)
HookWiring ─┤
McpTools   ─┘ ──fills ctx.merged_external_tools──> TemplateRendering ──> AgentFiles
```

## 4. Work packages — one commit each, in this exact order

Do **not** reorder. Each step must leave the suite green before you start the next.

### E1 — `ScaffoldContext`, with zero test changes

**This is the checkpoint that proves the refactor is behaviour-preserving.**

- New file `features/common/skills/welcome-ai-badger/scripts/scaffold_context.py`.
- A `@dataclass` holding exactly the attributes in §2's table, plus `skills` and
  `record_template`.
- `Scaffolder.__init__` builds one and stores it as `self.ctx`.
- **Every attribute in the table becomes a read/write property on `Scaffolder`** delegating to
  `self.ctx`, so all 103 existing constructions and every `s.notes` / `s.target` access keep
  working untouched.

**Hard acceptance for E1:** `git diff --stat` shows **zero lines changed under `tests/`**. If
you needed to change a test, the properties are wrong — fix the properties, not the test.

Python 3.8: use `field(default_factory=list)` for `notes`; no `slots=True` (3.10+).

### E2–E5 — the four leaves, one commit each

Order: `Extensions` → `StatusLineWiring` → `HookWiring` → `McpTools`.

For each:
1. Turn the mixin class into a plain collaborator class taking `ctx` in `__init__`.
2. `Scaffolder.__init__` instantiates it; the old public method becomes a one-line delegation.
3. **Public method names on `Scaffolder` do not change.** Tests call them; they must keep working.

`McpTools` additionally sets `ctx.merged_external_tools` instead of `self._merged_external_tools`.

### E6 — `TemplateRendering`

Same shape. Reads `ctx.merged_external_tools`. Also owns `ctx.carried_body`.

### E7 — `AgentFiles`

Same shape, but `__init__(self, ctx, template_rendering)`. Uses `record_template` from `ctx`.

### E8 — drop the mixin bases

`class Scaffolder:` — a plain class holding a context and six collaborators. The `Mixin` suffix
disappears from every class name (`McpToolsMixin` → `McpTools`, etc.).

### E9 — move internals-reaching tests onto the collaborator that owns them

Only tests that poke at a private method (`s._render_entry`, `s._merge_external_tools`, …).
Tests that construct `Scaffolder` and call public methods stay exactly as they are.

**Do NOT split the test files in this wave.** That is Wave 15 and it is out of scope.

---

## 5. Test cases you must write

### 5.1 The TDD entry point — write this FIRST, watch it fail

`tests/test_scaffold_context.py`:

```python
def test_each_collaborator_works_with_no_scaffolder_in_scope():
    """A collaborator takes a context and nothing else; today the mixins need a Scaffolder."""
```

Construct a `ScaffoldContext` by hand, instantiate each collaborator with it, call one public
method on each, assert it produces its expected effect. **This must fail today** — the mixins
cannot be instantiated alone. Run it and paste the failure into your first commit message.

### 5.2 Step-order golden master — the regression this refactor could silently cause

`run()`'s step order is load-bearing and recorded in `manifest.json.partial.completedSteps`
(`scaffold.py:769`).

```python
def test_the_scaffold_runs_its_steps_in_the_recorded_order(tmp_path, ...):
    """Composition must not reorder run(); completedSteps is the contract."""
```

Capture the exact `completedSteps` list on `main` **before** you start, paste it into the test
as a literal, and assert equality after every work package. If it changes, you have reordered
`run()` — revert and redo that step.

### 5.3 Per-collaborator construction tests

One per collaborator (six total): construct with a context, assert it works, assert no
`Scaffolder` is imported in that module.

### 5.4 The context is the only shared state

```python
def test_no_collaborator_reaches_another_through_self():
```

Assert that no collaborator module imports another collaborator module, with the single
documented exception of `agent_files` importing `template_rendering` (§3).

---

## 6. Acceptance checklist

Tick every line. A blank line is a blocked task, not a judgement call.

**Per work package (E1–E9):**
- [ ] `.venv/bin/python -m pytest -q` — 1430 passed, 17 skipped, or higher. **Never fewer.**
- [ ] `.venv/bin/python -m pylint scripts features` — exactly `10.00/10`
- [ ] `completedSteps` identical to the literal captured in 5.2
- [ ] Commit is one work package; `git show --stat` touches only that step's files

**E1 specifically:**
- [ ] `git diff --stat HEAD~1 -- tests/` outputs **nothing**

**Before pushing:**
- [ ] `.venv/bin/python scripts/validate.py --all`
- [ ] `.venv/bin/python scripts/index_build.py --check`
- [ ] `.venv/bin/python scripts/docs_guard.py`
- [ ] `.venv/bin/python scripts/deps_guard.py`
- [ ] `.venv/bin/python scripts/sync_plugin_skills.py --check`
- [ ] `node --test "tests/js/*.test.mjs"` — 24 pass
- [ ] Every collaborator has a construction test (5.3)
- [ ] `grep -rn "Mixin" features/common/skills/welcome-ai-badger/scripts/` returns nothing
- [ ] Branch `refactor/scaffold-collaborators` pushed. **No PR.**

---

## 7. Standing rules

- **TDD is mandatory.** Failing test first, every time. Run it, see it fail, then implement.
- **Do NOT bump `VERSION`, write a changelog, re-scaffold, or run `release_guard.py`.** The
  release is cut centrally. Say in your report that this is **patch**-worthy: no behaviour
  changes, no consumer-visible surface changes.
- **Push a branch; do not open a PR.**
- Stage files explicitly. **Never `git add -A`** — this is a shared checkout.
- Never stage `.idea/` or `__pycache__/`.
- Never hand-edit `skills/`, `.claude/skills/` or `.ai-badger/skills/` — regenerate with
  `scripts/sync_plugin_skills.py`. `features/…/scaffold.py` is the source; `skills/…` is its
  generated mirror.
- Use `.venv/bin/python`. `python3` on PATH is 3.14 and has no pytest. **Python 3.8 is the
  floor** — no `match`, no `X | Y` runtime unions, no `slots=True` dataclasses.
- Comments: 1–3 lines, contract not rationale. Test docstrings: one sentence or none.

## 8. Stop and ask if

- E1 cannot be done without touching a test — the property delegation has a hole worth a human
  decision.
- `completedSteps` changes and you cannot see why.
- You find a **seventh** collaborator's worth of behaviour hiding in `scaffold.py`.
- A cross-mixin edge exists that is not one of the three in §3.

## 9. Report back

Branch name; the E1 zero-test-diff proof; the `completedSteps` literal and that it never
changed; any cross-mixin edge you found beyond the three; and **every test you rewrote or
deleted, named individually, with what assertion changed**. A rewritten test is where a
regression hides.
