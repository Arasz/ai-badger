---
name: feed-badger
description: >-
  Harvest project-agnostic improvements from a repo back into the ai-badger framework via a
  draft PR. Use when a user wants to contribute additions upstream — "feed-badger", "contribute
  this back to the framework", "push my skill/persona/invariant changes to ai-badger", "harvest
  agnostic additions". Detects what changed beyond the original scaffold, classifies and
  generalizes the agnostic parts, places them into {stack}/{feature}, and opens a draft PR.
---

# feed-badger

The reverse of `welcome-ai-badger`: it finds framework-managed content you have added or
changed in a project, keeps only what is genuinely reusable, generalizes it, and contributes it
back to `ai-badger` as a **draft PR** for human review.

## Responsibility split

- **Scripts (mechanical):** `detect_additions.py` diffs `.ai-badger/` against `manifest.json`
  and lists candidates; `open_pr.py` does the git branch/commit/push + `gh pr create --draft`.
- **You (creative):** classify each candidate (agnostic / generalizable / project-specific),
  drop project-specific ones with a reason, **generalize** the keepers (strip project paths,
  domain terms, repo names), and **place** each into the correct `{stack}/{feature}/` path in an
  ai-badger checkout.

## Flow

1. **Detect candidates** (from the target repo root):
   ```bash
   python3 "$AI_BADGER/skills/feed-badger/scripts/detect_additions.py" --target . --root "$AI_BADGER"
   ```
   Emits `new` (files not from the framework) and `changed` (files edited beyond the scaffold)
   candidates, by feature.

2. **Classify & generalize.** For each candidate decide agnostic / generalizable /
   project-specific. Drop project-specific ones (state why). For the keepers, rewrite to remove
   anything project-coupled — no repo names, no domain nouns, no absolute paths. Decide the
   target stack (or `common`) and feature. A brand-new stack or feature is allowed.

3. **Place into an ai-badger checkout.** Clone or reuse a checkout of `Arasz/ai-badger`, write
   each generalized file to its `{stack}/{feature}/` path, then regenerate the index:
   ```bash
   python3 "<checkout>/scripts/index_build.py"
   python3 "<checkout>/scripts/validate.py" --all
   ```

4. **Open a draft PR.** Write a PR body summarizing each contribution and why it is agnostic,
   then:
   ```bash
   python3 "$AI_BADGER/skills/feed-badger/scripts/open_pr.py" \
     --checkout <checkout> --branch feed/<slug> \
     --title "feed: <summary>" --body-file <body.md> --repo Arasz/ai-badger
   ```
   Use `--dry-run` to preview the git/gh commands without executing (useful for testing).

## Rules

- **Draft, always.** Contributions land as draft PRs; a human reviews and merges. Never
  auto-merge.
- **Agnostic bar is high.** When unsure whether something is reusable, keep it in the project,
  not the framework. Better to under-contribute than to pollute the catalog.
- **Provenance drives detection.** `feed-badger` only works on repos scaffolded by ai-badger
  (those with `.ai-badger/manifest.json`).
