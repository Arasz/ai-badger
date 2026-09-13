# ADR-0030 — Vendor Archify, and make diagrams archify-first with a Mermaid fallback

**Date:** 2026-09-13
**Status:** Accepted (2026-09-13, 0.171.0)
**Author:** Rafał Araszkiewicz (Arasz) with pi (task `aib-archify-diagram-skill-default-integration`)
**Extends:** ADR-0009/ADR-0024 (vendored verbatim copies), ADR-0018 (a skill declares its own
scope), ADR-0028 (the common catalog ships by default)
**Scope:** `features/common/skills/archify/`, `tooling/vendor_archify.py`, the new
`archify-diagrams` invariant, `dependency_check.py`'s `system` ecosystem

## Context

The catalog has no diagram-authoring capability of its own. Five skills and templates name
Mermaid, which is ideal for a diagram that renders inline in committed Markdown but produces no
standalone, presentable artifact. Upstream [Archify](https://github.com/tt-a1i/archify) is an MIT
skill (two copyright holders: tt-a1i and Cocoon AI) that renders typed JSON into validated,
self-contained interactive HTML across five diagram types, with no runtime npm dependencies and
Node.js >= 18 as its only requirement. It publishes a canonical staged packet as a release asset
(`archify.zip`), not as a frozen directory in the tag tree alone.

ai-badger has vendored byte-equal code before (`engine/badger_store.py`, ADR-0009/0024) and has a
one-declaration-of-scope rule (ADR-0018). The alternative — installing the skill from an external
source at scaffold time — was rejected because it is network-dependent, unpinned at use time, and
the upstream installer does not cover pi, Hermes or Copilot, leaving configured agents without the
capability.

## Decision

Four rulings:

1. **Vendor the v2.16.0 release packet under `features/common/skills/archify/`,** byte-identical
   for the 76 upstream files, with `LICENSE` and `THIRD_PARTY_NOTICES.md` (the latter backfilled
   from upstream `main`; v2.16.0 ships none, and `brand-marks/catalog.json` is byte-identical
   between the two, so the notice applies exactly). `vendor.json` pins the repo, tag, commit and
   release-asset sha256, plus a per-file sha256. `tooling/vendor_archify.py --check` verifies the
   tree offline; re-vendoring is an explicit
   `--revendor <archify.zip> --expect-sha256 <sha>` run whose expected sha comes from the command
   line, never from the manifest it rewrites.
2. **The skill declares `scope: default`** (ADR-0018), so it reaches every scaffold, the plugin
   copy, and existing consumers on their next `den-refresh`. A project that does not want it
   declines with `config.exclude.skills: ["archify"]`.
3. **Archify is the catalog's default diagram authoring tool,** stated once as the common
   invariant `archify-diagrams.md`: Mermaid is the fallback for a missing Node 18+ runtime, for a
   diagram that must render inline in committed Markdown, and when the user asks for Mermaid or
   text. The adaptation of upstream's `SKILL.md` keeps that fallback in the skill body and in its
   `description`, because plugin-only consumers never receive invariants.
4. **Node.js 18+ is a `system` dependency, detect-only.** `dependency_check.py` detects the binary
   with `shutil.which` in report and execute modes, hints when it is missing, and installs only
   when a declared `command` exists and `--execute` was passed. The archify entry declares no
   command, so a missing Node can never trigger an install; a Node older than 18 that exists on
   PATH reports as present, and the version floor is enforced at use time by
   `node bin/archify.mjs doctor` with the Mermaid fallback as the documented degradation.

## Consequences

**Positive.** Polished, validated, standalone artifacts with no install step; offline-verifiable
provenance; one documented re-vendor procedure; clean degradation instead of a failed task when
the runtime is absent.

**Negative.** ~17.7 MB added to the working tree across three copies (the feature tree, the plugin
copy, and the self-scaffolded `.ai-badger/` mirror) — pack growth is only ~1.1-1.5 MB because git
stores one blob set for byte-identical copies. The vendored surface is upstream's to change and
stays pinned until someone re-vendors. Node 18+ becomes a de-facto runtime for one default skill.
The upstream update checker makes an opt-out network call
(`ARCHIFY_UPDATE_CHECK_DISABLED=1`). A Node older than 18 is reported as present by the dependency
check (accepted residual; `doctor` is the floor check).

**Neutral.** The plugin copy is a pointer `SKILL.md` plus `SKILL.full.md`, like every non-bootstrap
skill. The routing invariant is scaffold-only, which is acceptable because the plugin copy carries
the degradation policy in its body and description. Hermes discovery requires an install run
(namespace symlinks); Copilot's cloud agent following committed relative symlinks and providing
Node at skill-execution time is unverified — both degrade to Mermaid.

## Alternatives

- **External skill source (`skills-source.json`/`skills.json`)** — no runtime installation, no
  offline determinism, and uncovered pi/Hermes/Copilot paths.
- **Fetch upstream at use time** — unpinned and network-dependent.
- **A first-party Mermaid-only rewrite** — leaves the ask unmet and duplicates upstream.
- **`scope: optIn`** — contradicts the owner's "by default" ruling.
- **A trimmed packet (drop the rendered `examples/*.html`)** — deferred; the trim is the documented
  escape hatch if the working-tree size ever bites, since those files are regenerable by upstream's
  `scripts/render-examples.mjs`.
