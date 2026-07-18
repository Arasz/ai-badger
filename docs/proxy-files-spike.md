# Feature plan: proxy files for agent-discovered instructions (needs a spike)

**Status:** documented plan only — not built, not scheduled. See "Out of scope" (§13) in
[`ai-badger-framework-design.md`](ai-badger-framework-design.md).

## Today

`scaffold.py` treats `.ai-badger/` as the single source of truth for a project's agent
configuration, but the agent CLIs (`claude`, `copilot`, `junie`) don't look there — they
discover instructions at fixed conventional paths. So for every file that is *core to agent
performance* and *discovered by convention*, `scaffold.py` writes a **full copy** into that
conventional location:

- `.ai-badger/CLAUDE.md` → copied to `CLAUDE.md`
- `.ai-badger/copilot-instructions.md` → copied to `.github/copilot-instructions.md`
- `.ai-badger/instructions/*.md` → copied to `.github/instructions/*.instructions.md`
- `.ai-badger/AGENTS.md` → copied to `.junie/AGENTS.md`

Each copy carries a header noting that `.ai-badger/` is the actual source of truth and the
file is regenerated from there. This works, but it means every scaffold (and every re-scaffold)
duplicates content, and a project can drift if someone edits the copy directly instead of the
`.ai-badger/` source — `manifest.json` provenance and `scaffold.py` idempotency are what keep
that in check today, not the file layout itself.

## The spike

Replace the full copies with **thin proxy files** — small stub files at the same conventional
paths that simply delegate the agent to `.ai-badger/` (e.g. "read
`.ai-badger/CLAUDE.md` for your instructions") instead of duplicating the content.

This only works **if** the target agent CLI actually follows such a pointer/stub instead of
just reading the stub's literal (tiny) content and stopping there.

## Open question

**Do the `claude`, `copilot`, and `junie` CLIs follow a pointer/stub placed at their
conventional instruction path, or do they treat whatever bytes are physically at that path as
the complete instruction set?**

This is unverified for all three:

- `claude` (`CLAUDE.md`): Claude Code is known to support `@path/to/file` import syntax inside
  `CLAUDE.md` in some contexts — if that import mechanism is reliably followed at project-root
  `CLAUDE.md` load time, a one-line `@.ai-badger/CLAUDE.md` proxy could work. Needs
  confirmation against current Claude Code behavior, not assumed from memory.
- `copilot` (`.github/copilot-instructions.md`): the design doc already notes "Copilot needs
  the copies because its CLI won't follow a reference" (§8) — this was an explicit reason the
  copy-vs-reference rule exists in the first place. A proxy file is likely a non-starter for
  Copilot unless that has changed; needs re-verification, not just trusting the prior note.
- `junie` (`.junie/AGENTS.md`): no prior finding either way — unverified.

## Risk

- If any of the three agent CLIs does **not** follow a proxy, that agent silently loses its
  real instructions (it would only see the stub's few lines) — a much worse failure mode than
  today's "copy can drift," because the agent doesn't even see the drifted content, it sees
  almost nothing. Any implementation must **fail loud** (e.g. `scaffold.py` verifies the proxy
  mechanism per-agent before relying on it, falling back to a full copy otherwise) rather than
  silently switching an agent to a broken proxy.
- Behavior may differ between IDE-integrated and CLI-only invocations of the same agent, and
  may change across agent CLI versions without notice — a proxy mechanism validated once could
  regress silently on an agent update.
- Even where a proxy works, some CLIs may only follow it from specific working directories or
  invocation modes, which would need to be enumerated, not assumed universal.

## Proposed investigation

1. For each agent (`claude`, `copilot`, `junie`), build a minimal reproduction: a proxy stub at
   the conventional path pointing at a `.ai-badger/`-style sibling file with a unique, greppable
   marker string in it, and confirm (by asking the agent something only the marker file could
   answer) whether the agent actually consumed it.
2. Test both repo-scope and any user-scope equivalent, and both CLI and IDE-integrated
   invocation where applicable.
3. If a proxy mechanism is confirmed for an agent, define the exact stub format ai-badger will
   generate for it and how `scaffold.py` would detect the mechanism is unsupported (version
   pinning, a capability probe, or an explicit allow-list) so it falls back safely to a full
   copy rather than assuming support.
4. Only after all three agents have a confirmed-safe path (proxy or explicit fallback) should
   this move from spike to an implementation task, with its own design note updating §8 of
   [`ai-badger-framework-design.md`](ai-badger-framework-design.md) and
   [`framework-architecture.md`](framework-architecture.md).

Until then, `scaffold.py` continues writing full copies as described in
[`framework-architecture.md`](framework-architecture.md#6-target-repo-structure-ai-badger).
