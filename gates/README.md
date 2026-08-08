# Writing a gate

Five rules, each with the thing that enforces it. They are here because this repo has broken
every one of them at least once, and a gate that breaks one of them is worse than no gate: it
reports success on a defect nobody is looking for any more.

1. **Dispatch it from a lane.** Add the gate to `$LANES` in `.lefthook/pre-push/verify.sh`. A gate
   that nothing runs proves nothing about a push, however correct it is.
   `tests/test_every_check_can_fail.py` fails the build for a discovered gate that no lane
   reaches — that check exists because 0.99.0 shipped a gate nobody enumerated.

2. **Register a provocation.** Add an entry to `REGISTRY` in `tests/test_every_check_can_fail.py`:
   a known-bad state built under `tmp_path`, actually run, plus the same fixture without the
   defect. Both answers must appear. `EXEMPTIONS` is a debt list, not a place to park a new gate.

3. **Derive the lists it compares.** Read the tree, the manifest or the index rather than
   maintaining a parallel copy of it in the gate. Every hand-written allowlist here has drifted
   from its twin; 0.101.0's fix was to delete `REGENERATED_FEATURES` and read the per-entry flag
   the scaffolder already writes, and 0.104.0's was to delete `SKILL_SCOPES` and read `SKILL.md`.

4. **Fail open on internal error when it gates a tool.** A gate wired into a hook stands between
   an agent and its tool call. A crash, a missing sibling module or an unreadable config must let
   the call through with a note, never block it — a gate that bricks the harness gets disabled,
   and then it is not a gate. A gate that only runs at push time may fail closed.

5. **Prove it can fail before trusting it.** Break the thing on purpose, watch the gate go red,
   restore it, watch it go green — and paste both into the PR. Rule 2 makes this permanent; this
   rule is about the first time, before the gate is believed.

Shared finding shape, exit codes and reporting live in `gate_report.py`. The recurring defect this
whole directory guards against is written up in the module docstring of
`tests/test_every_check_can_fail.py`, with the four historical cases that motivated it.
