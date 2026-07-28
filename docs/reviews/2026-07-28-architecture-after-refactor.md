# Architecture after Wave 6 and ADR-0011 — measured against the baseline

**Measured:** 2026-07-28 · **Commit:** `2abfb90` · **Tag:** `ai-badger--v0.37.0`
**Baseline:** [`2026-07-28-architecture-baseline.md`](2026-07-28-architecture-baseline.md) at
`9a9cded` / `v0.36.2` · **Method:** full rebuild both times, per the baseline's §5 warning.

**Two of the six predictions were wrong.** They are reported first, because a prediction recorded
in advance is only worth something if the failures are stated.

## 1. Predictions that failed

### `Scaffolder` got **bigger**, not smaller

| | Baseline | After | |
|---|---:|---:|---|
| `Scaffolder` | 555 | **583** | **+28** |

The baseline predicted it would "drop well below 555 lines; it should become a constructor plus
delegations." It became exactly that and still grew.

The mixin bodies left, but what replaced them is not free: twelve read/write context properties
(the price of E1's zero-test-diff constraint), the construction of six collaborators, and a
delegation for every public method that used to be inherited. Inheritance made those lines
invisible; composition makes them explicit. The 994 lines of mixin bodies did move out — into
six classes that now sum to 1,022 as independent collaborators.

**The honest reading: this refactor did not reduce code. It converted implicit coupling into
explicit wiring, and explicit wiring costs lines.** The baseline flagged that risk for the
*total* and predicted it anyway for `Scaffolder`. That was wrong.

### Community count fell instead of rising

11 → **10**. The baseline predicted phase 2 would push it up by splitting `scripts-root`. Two
communities did appear (`engine-root`, `tooling-items`), but three collapsed —
`scripts-root-skill`, `hooks-root` and `adjustments-adjust-prune` were absorbed. Net −1.

Community detection is Leiden, which re-partitions globally on every run; the baseline said to
compare sizes and cohesion rather than IDs, and should have said the same about the count.
**Community count is not a quality metric and should not have been predicted.**

## 2. Predictions that held

| Prediction | Result |
|---|---|
| Zero `*Mixin` classes remain | ✅ **0** (was 6) |
| `ScaffoldContext` appears | ✅ |
| Six independently constructible collaborators | ✅ 17 tests construct each from a context alone |
| `engine`/`tooling` communities appear | ✅ `engine-root` (44), `tooling-items` (38) |
| Cross-community edges stay 0 | ✅ **0**, and 0 warnings |
| Hub table barely moves | ✅ still all test helpers; `_config` 148 → 155 |

Cohesion of the main production community rose: **0.1821 → 0.1949**. Small, and the single
number that moved in the direction the refactor was for.

## 3. Full comparison

| Metric | Baseline (0.36.2) | After (0.37.0) | Δ |
|---|---:|---:|---|
| Files | 158 | 161 | +3 |
| Nodes | 2,587 | 2,633 | +46 |
| Edges | 24,603 | 25,106 | +503 |
| Communities | 11 | 10 | −1 |
| Flows | 109 | 101 | −8 |
| Cross-community edges | 0 | 0 | — |
| Warnings | 0 | 0 | — |
| Tests | 1,433 | 1,467 | +34 |

### Communities

| Community | Baseline | After |
|---|---:|---:|
| `tests-fake` | 1,680 (0.2461) | 1,708 (0.2457) |
| `scripts-root` | 436 (0.1821) | **529 (0.1949)** |
| `scripts-root-skill` | 82 (0.1413) | *absorbed* |
| `hooks-root` | 78 (0.2226) | *absorbed* |
| `gates-check` | 52 (0.2022) | 52 (0.2022) |
| **`engine-root`** | — | **44 (0.1760)** |
| **`tooling-items`** | — | **38 (0.1133)** |
| `scripts-cmd` | 33 (0.2424) | 38 (0.2244) |
| `js-model` | 27 (0.4252) | 27 (0.4252) |

### Classes in `features/`

| Class | Baseline | After |
|---|---:|---:|
| `Scaffolder` | 555 | **583** |
| `McpToolsMixin` → `McpTools` | 342 | 353 |
| `ExtensionsMixin` → `Extensions` | 169 | 173 |
| `HookWiringMixin` → `HookWiring` | 148 | 151 |
| `AgentFilesMixin` → `AgentFiles` | 122 | 126 |
| `TemplateRenderingMixin` → `TemplateRendering` | 121 | 124 |
| `StatusLineWiringMixin` → `StatusLineWiring` | 92 | 95 |

## 4. So did the parameters improve?

**Structurally, yes; by size, no.**

What the graph can see improved: the directory split is real and visible (`engine-root`,
`tooling-items`, `gates-check` are three distinct communities where there was one `scripts/`
bucket), cohesion of the main production community rose, and coupling stayed clean at zero
cross-community edges.

What the graph cannot see is the actual point of Wave 6, and it is worth being clear that the
numbers here do **not** demonstrate it: six classes that could not previously be instantiated
without a `Scaffolder` now can be, proven by 17 tests that construct each from a context alone.
A line count cannot express that, and the line count moved the wrong way.

**If the goal had been "make the codebase smaller", this refactor failed.** It was not, and the
baseline said so before the measurement: *"line count is not the metric; independent
constructibility and cohesion are."* That framing is the only reason the +28 on `Scaffolder`
reads as a known cost rather than a surprise.

## 5. Follow-up this suggests

- `Scaffolder` at 583 lines is still the largest class in the codebase. It keeps **five** public
  delegations, of which **four have no caller on `Scaffolder`** — `wire_statusline_capture`,
  `unwire_statusline_capture`, `assemble_instructions_doc` and `assemble_hermes_doc`. Only
  `wire_hooks` is called. Those four are the obvious first cut.

  Counted with care, because the naive grep is wrong: `.assemble_instructions_doc(` also matches
  `self.rendering.assemble_instructions_doc(…)`, which is `run()` calling the **collaborator**
  directly and bypassing the delegation entirely. Exclude the collaborator receivers before
  counting.
- `tooling-items` has the lowest cohesion of any production community (0.1133) — expected for
  five scripts that share a directory and little else, but worth watching if it grows.
- The hub table is still entirely test helpers. Wave 15 (splitting the test files) is the change
  that would move it.
