# Archify diagram skill — plan proposal (API engineer: contracts)

Task `aib-archify-diagram-skill-default-integration`, target 0.171.0. Read-only planning lane.
Basis: `docs/work/2026-09-13-archify-diagram-skill-research.md` (all § refs below) + sources
re-read this session: upstream v2.16.0 tree at `/tmp/archify-clone`, `gates/skills_lint.py`,
`features/common/skills/welcome-ai-badger/scripts/dependency_check.py`,
`schemas/dependencies.schema.json`, `tests/test_dependency_check.py`,
`features/common/skills/qa/SKILL.md` (frontmatter model), upstream `skill-release.json`
(version 2.16.0), upstream `package.json` (`engines.node >= 18`).

Measured this session (not carried over): `references_without_conditions` on the upstream
`SKILL.md` returns `[]` — zero rule-8 violations; body = 127 lines / 15,215 chars (proxy 3804,
headroom 373 lines / ~4.7K chars). Upstream `stage-clean-skill.mjs` (main) was read in full;
exclusion semantics below are quoted from it, not from the research summary.

## Contract 1 — `tooling/vendor_archify.py` (re-vendor + integrity tool)

Verdict: build the Python tool — stdlib-only (repo invariant; `--check` must run where Node
may be absent), but cheaper than the research recommendation: `--check` (offline gate) +
`--tag` (network re-vendor from a tag tarball with the exclusion list applied in Python).
Rejected: (a) procedure-only (manual steps drift; this repo already gates byte-equality);
(b) re-implementing upstream's TOCTOU-hardened stager (snapshot fds, mode/symlink refusal) —
that is upstream's publish-to-strangers threat model, not a maintainer-run vendor op; document
the delta instead; (c) shelling out to upstream's own stager via Node (couples a Python gate
to Node+git and breaks offline `--check`).

Staging rules (copied from upstream `scripts/stage-clean-skill.mjs`): exclude exactly
`archify/test/`, `archify/package-lock.json`, `archify/scripts/generate-brand-marks.mjs`,
`archify/scripts/generate-validators.mjs`, plus path segments `node_modules`, `.DS_Store`,
`.hive`, `.workbuddy`, `.validator-check-*`; refuse symlinks; clean `package.json` by
dropping `scripts` + `devDependencies` (keep `overrides`, `engines`, `bin`). Upstream's
`build-zip.sh` Node-22-canonical-bytes requirement is NOT copied (we vendor a tree, not bytes).

CLI: `vendor_archify.py --check` (offline; exit 0 clean, 1 divergence — prints
`MISSING/EXTRA/CHANGED <relpath>` per file); `vendor_archify.py --tag vX.Y.Z` (network:
fetch codeload tarball for the tag, apply exclusions + package.json cleaning + §3
frontmatter adaptation, write tree + `vendor.json`; exit 0 staged, 1 dirty target or
adaptation mismatch, 2 network failure — never partial-write: stage to temp dir, rename).
`--check` never touches the network. `--tag` refuses when the feature dir has uncommitted
changes (`git status --porcelain -- <dir>` non-empty → exit 1).

`vendor.json` (lives beside the tree, ai-badger addition): `{upstream:{repo,tag,commit},
adaptation_rev, adapted_frontmatter_sha256, upstream_body_sha256,
files:{relpath:sha256}, extra_files:["VENDOR.md","vendor.json","THIRD_PARTY_NOTICES.md"]}`.
`--check` recomputes per-file sha256 over the tree minus `extra_files`; anything else
untracked → EXTRA (divergence). Frontmatter adaptation is deterministic: fixed template in
the tool (keyed by `adaptation_rev`); `--check` splits current `SKILL.md`, hashes the body,
compares to `upstream_body_sha256` (body must stay byte-identical to upstream) and the
frontmatter hash to `adapted_frontmatter_sha256`. `LICENSE` is upstream packet content
(kept byte-identical, hashed like any file). `THIRD_PARTY_NOTICES.md` is backfilled from
upstream main at first vendor (v2.16.0 has none; brand-marks embed Simple Icons 16.28.0),
recorded in `extra_files`, never hashed against upstream. `VENDOR.md` records provenance +
the stager delta in prose.

Failure modes: tag tarball 404/checksum unknown → exit 2, tree untouched; upstream body
drift under same tag (tag moved) → `CHANGED SKILL.md body` + recorded commit mismatch → exit 1;
`--check` on Python <3.10 → hard error (repo floor).

- Acceptance: `tooling/vendor_archify.py --check` → exit 0, prints `ok archify vendor v2.16.0 <n> files`.
- Acceptance: delete one byte from `features/common/skills/archify/bin/archify.mjs` → `--check`
  exits 1 printing `CHANGED bin/archify.mjs`; restore → exit 0.
- Acceptance: drop an extra file in the tree → `--check` exits 1 printing `EXTRA <path>`.
- Acceptance: `vendor_archify.py --tag v9.9.9` with no network → exit 2, tree byte-identical
  (`git status --porcelain -- features/common/skills/archify` empty).

## Contract 2 — `dependency_check.py` `system` ecosystem + archify Node entry

Verdict: implement `system` in `dependency_check.py`; **no schema change** — verified
`schemas/dependencies.schema.json` already allows `ecosystem: system` (enum) and `command`
(string) with `additionalProperties: false`, so the archify entry validates as-is. The
research recommendation stands, minus the schema edit it hedged on.

Semantics: `package` names the binary; detection = `shutil.which("node")`, then read-only
`node --version` (fixed argv, `shell=False`) parsed to major ≥ 18 (upstream `engines`).
Present + ≥18 → `already_present`. Missing or <18 → hint, never error (Mermaid fallback
means scaffold must succeed without Node). Install runs only when `allow_install` AND a
non-empty `command` is declared: `shlex.split(command)` → `subprocess.run(..., shell=False,
timeout=120)`; non-zero/timeout → `errors`. The archify entry deliberately declares **no**
`command` (no universal Node installer belongs in catalog data; brew/apt/choco differ) → it
can never auto-install; under `--execute` it stays a hint. Shapes unchanged:
`{installed, already_present, errors, hints}`. Security (I7 consent gate + catalog-data-is-data):
`command` text is never interpolated into a shell; detection execs only the fixed
`[package, --version]` argv; nothing runs without `--execute`.

Entry (`features/common/dependencies.json`): `{feature:"archify",
path:"features/common/skills/archify", dependencies:[{name:"Node.js 18+ (Archify diagram
renderer)", ecosystem:"system", package:"node", note:"Without it Archify commands are
skipped and diagrams fall back to Mermaid; install Node.js 18+ from https://nodejs.org."}]}`.
Scaffold note (via existing `_check_dependencies` hint path; relabel, not "optional
dependency:"): `Node.js 18+ not found on PATH — Archify diagrams unavailable, Mermaid
fallback applies. Install Node.js 18+ (https://nodejs.org).`

Failure modes: `node` present but v16 → hint names found version + floor; `node --version`
hangs → timeout treated as absent (hint, not error); `command` declared but failing →
`errors: ["node: <command> failed — <stderr>"]`, exit 1 preserved by `main`.

- Acceptance: `run_dependency_check(root, target, features=["archify"])` with `node` stubbed
  absent → `{"installed":[],"already_present":[],"errors":[],"hints":["Node.js 18+ not found…"]}`.
- Acceptance: same call with `shutil.which → ".../node"` and `node --version → v22.x` →
  `already_present == ["node"]`, no hints.
- Acceptance: `node --version → v16.y` → hint contains `v16` and `>=18`.
- Acceptance: system entry **with** `command`, `allow_install=True` → subprocess argv equals
  `shlex.split(command)` (assert `shell` not passed / False); without `allow_install` →
  `subprocess.run` uncalled (extends existing `TestInstallConsent`).

## Contract 3 — adapted `features/common/skills/archify/SKILL.md`

Frontmatter (exact; rule-10 keys + rule-12 `scope: default`; model = `qa/SKILL.md`):

```yaml
name: archify
description: >-
  Use when the user asks to visualize system architecture, infrastructure, cloud/security
  topology, technical workflows, API call sequences, request lifecycles, data pipelines or
  state machines — or to convert/beautify a Mermaid diagram — as a polished standalone HTML
  diagram. Falls back to Mermaid when Node.js 18+ is unavailable.
version: 2.16.0
author: tt-a1i
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [diagrams, architecture, workflows, visualization, mermaid]
    related_skills: [documentation, task, differential-feature-refactor, complete-project-scope-code-review]
```

(`author: tt-a1i` preserves upstream attribution; `version` tracks upstream, bumped only by
`--tag` re-vendor. Description ~430 chars, starts "Use when".)

Body edits (minimal; upstream body otherwise byte-identical per Contract 1): (a) rule 8 —
measured zero violations, but line 82's `See references/authoring-contract.md…` passes only
because line 81 contains "When needed" (adjacency accident). Pin it: `…for details when you
need field enums or spacing math.` (one-word-class fix, no re-wrap risk). Lines 20 (numbered
step, exempt), 94, 114, 120 (own conditions), 131 (`When shell access…` in-window) need no
change. (b) Add `## Gotchas` (rule 9) covering: run offline-sensitive work with
`ARCHIFY_UPDATE_CHECK_DISABLED=1` (the vendored copy is pinned by `vendor.json` — its
`scripts/check-update.mjs` notice/ack workflow does not apply, never mutate the skill);
`visual-check` exit 2 = Chrome absent (skipped, not failure); failed `deliver` preserves the
stale last-good HTML (never `visual-check` that path); `meta.quality_profile` must be spelled
exactly or validation misleads; `validate` receipt with 4 checks ≠ showcase (needs 9, 0
errors, 0 warnings). (c) Add `## When NOT to Use` + Mermaid-fallback text: use Mermaid when
Node.js 18+ is missing, for quick inline docs diagrams, or when the consumer explicitly asks
for Mermaid source; Archify is the default for committed architecture/workflow/sequence/
dataflow/lifecycle deliverables. Budget fits: additions ~60 lines / ~3K chars stay within
500 lines and proxy 5000 (3804 + ~750). Rejected: thin-wrapper-around-byte-identical-upstream
(two-file procedure, per research) — adaptation stays in one file, guarded by
`upstream_body_sha256`.

- Acceptance: `gates/skills_lint.py --root .` → `ok skills lint — <n> SKILL.md checked`, exit 0.
- Acceptance: `python3 -c` importing `references_without_conditions` on the adapted file → `[]`.
- Acceptance: `awk '/^---$/{c++} c==2{body=1} body' SKILL.md | wc -lc` → lines ≤ 500, chars/4 ≤ 5000.
- Acceptance: `head -c 8` of description fold == `Use when`; `grep -c '^## Gotchas' SKILL.md` == 1.
