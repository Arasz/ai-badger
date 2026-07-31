---
name: create-refinement-document
description: >-
  Use when a design, refactor or review document needs a per-decision ruling from one human
  reviewer and the answers must come back attached to the decision they belong to. Triggers:
  pasting a long document into chat and getting a wall of prose back, an answer that can't be
  matched to its question, a reviewer hand-editing answer slots in markdown, or a set of
  decisions that must each be approved, changed, rejected or deferred before work is scoped.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [review, decisions, design, feedback]
    related_skills: [differential-feature-refactor]
---

# Create a refinement document

Generate a **review form** — one card per decision, a verdict control and a notes box — that
emits structured markdown. The reviewer clicks and types; the agent gets back a file where every
answer is bound to its decision by construction, not by paragraph order.

**Why this exists.** Prose feedback loses the mapping from answer to question. Answer slots
hand-edited into markdown are better but still lose content: a line-shaped slot hid multi-line
answers, and a reader parsing only the marker line reported six points unanswered when every one
had a written answer beneath it. A form cannot lose the mapping — the DOM enforces it.

## Two variants, one interface

| Variant | Reviewer does | Agent gets it back by |
|---|---|---|
| **Local file** (`file://…/<slug>-review.html`) — **prefer this** | opens the file, answers, clicks **Save feedback** | watching for the result file on disk; no copy-paste |
| **Artifact** (published to claude.ai) | answers, clicks **Copy feedback**, pastes into chat | reading the pasted block |

Same template, same markdown output. Use the Artifact only when the reviewer is not on a machine
you can watch — an artifact page has no filesystem and cannot write next to itself.

## Agent-side protocol

1. **Write the form** from `references/form-template.html` to `<date>-<slug>-review.html`, beside
   the document it reviews — whatever directory that project keeps design and review documents in
   (`docs/designs/` unless it keeps another). Fill the `DECISIONS` array and all per-review
   `CONFIG` fields: `title`, `subtitle`, `source`, `outName`, `expectedDir`, and a unique
   `storageKey` such as `refinement:<slug>:v1`. Do not create a new doc home for it.
2. **Pre-create nothing that could read as a real answer.** Do not write a stub result file, do
   not seed `localStorage`, do not fill any verdict "as an example". A pre-created result file
   makes the watch fire instantly and gets ingested as a review that never happened.
3. **Start the watch** (below) before telling the reviewer the form is ready.
4. **Tell the reviewer to press Clear first** if they have used a review form before — see the
   shared-origin hazard below. The Clear button exists for exactly this.
5. **Ingest** when the file appears: **read the file**, do not trust the notification's timing.
   Check the trailing `<!-- end refinement feedback -->` marker; without it the file was caught
   mid-write — re-read.
6. **Read every note in full.** A note may be a counter-question. That is a legitimate answer and
   means the decision stays open. Verdict alone is never the whole answer.
7. **Reconcile the `## Not answered` list explicitly.** Silence is not consent. Ask again or
   record the item as still open — never resolve it yourself.

### The watch

```bash
OUT="/abs/path/docs/designs/2026-01-15-import-pipeline-feedback.md"
for i in $(seq 1 720); do [ -f "$OUT" ] && break; sleep 5; done   # capped: 720 × 5s = 1h
[ -f "$OUT" ] && echo "feedback landed at $OUT" || echo "timed out, no feedback"
```

Run it with `run_in_background: true`. The cap is mandatory: a watch with no stopping condition
is a loop nobody can answer "what ends this?" for, and it outlives the session that started it.
The example uses POSIX shell syntax and is intended for macOS/Linux; on another platform, use an
equivalent finite watcher and preserve the same one-hour cap.

**Caveats.** It fires on file *creation*: a reviewer who saves twice produces one notification,
not two, so the notification tells you a review exists, never that it is the final one — re-read
the file at ingest and re-read again if the reviewer says they changed something. If the reviewer
fell back to `a[download]`, the file is in the browser's download directory, not `$OUT`; the form
tells them so, but also check `~/Downloads/<OUT_NAME>` before declaring a timeout.

## Saving from a `file://` page — what was verified

Measured on this machine, real Google **Chrome 150.0.7871.181** (macOS, `--headless=new`, fresh
profile) plus Playwright **Firefox 153** and **WebKit 605** builds, all on a `file://` page:

| Fact | Result |
|---|---|
| `window.isSecureContext` on `file://` | `true` in all three engines |
| `showSaveFilePicker` / `showDirectoryPicker` | **Chromium: `function`. Firefox: `undefined`. WebKit: `undefined`.** |
| Calling it without a user gesture | `SecurityError: Must be handling a user gesture to show a file picker.` — **must run inside the click handler** |
| `startIn` with a filesystem path | `TypeError: … not a valid enum value of type WellKnownDirectory` — **you cannot preset the picker to the HTML file's own folder** |
| `localStorage`, `indexedDB` on `file://` | both work |
| `a[download]`, `blob:` URLs | supported in all three |
| `navigator.clipboard.writeText` | rejects `NotAllowedError` without a gesture; resolves with one |
| **All `file://` pages share one origin (`file://`)** | a value set by `pageA.html` was read back by `subdir/pageB.html` |

**Unverified — say so rather than assert:**

| Claim | Check that would settle it |
|---|---|
| The picker actually opens and the bytes land on disk. Headless returns `AbortError` because there is no picker UI, so only the *gesture requirement* was proven, not the write. | Open the form in headful Chrome, click Save, `ls` the chosen path. |
| Safari.app behaves like Playwright's WebKit build. | Open the form in Safari, run `typeof window.showSaveFilePicker` in the Web Inspector console. |
| `a[download]` on `file://` saves silently vs. opening a Save-as dialog. | Depends on the browser's "ask where to save" setting; click it once and watch. |
| macOS save dialogs accept a pasted path via ⌘⇧G. | Standard macOS behaviour, not re-tested here; the form offers it as a hint, not a promise. |

**Consequences baked into the template:**

- The save chain is **remembered directory → one-time directory grant → `a[download]` → clipboard →
  always-visible textarea**, and the UI **names which one it used and where the file went**. A save
  that silently lands somewhere unexpected is worse than no save.
- An `AbortError` means the reviewer cancelled — the chain **stops**, it does not fall through to a
  download the reviewer didn't ask for.
- **The folder is asked for once, not once per save.** Reviewer feedback from the first real run:
  *"save feedback should use the same dir as html file — selection is a noise."* A `file://` page cannot discover its
  own folder and `startIn` takes only the `WellKnownDirectory` enum, so the folder cannot be preset.
  What it can do is grant the directory **once**, persist the `FileSystemDirectoryHandle` in
  IndexedDB, and write silently thereafter. Handles survive reload; the *permission* does not, so it
  is re-requested inside the click handler where a gesture exists. Point the one dialog at the folder
  holding the HTML and it never returns.
- The IndexedDB key is `<storageKey>:dir`, so it is **per review** for the same reason `localStorage`
  is — every `file://` page shares one origin.

**Verified for the remembered-directory path** (Chrome 150, `--headless=new`, served over
`http://127.0.0.1` since Playwright blocks `file:`):

| Fact | Result |
|---|---|
| `showDirectoryPicker` exposed | `function` |
| `indexedDB` open / `put` / `get` round-trip | works |
| Form still renders with the new chain — 13 verdict groups, 4 buttons, no JS errors | ✅ |

**Unverified — say so rather than assert:**

| Claim | Check that would settle it |
|---|---|
| A real `FileSystemDirectoryHandle` survives the IndexedDB round-trip. Only a plain object was round-tripped; handles are structured-cloneable *per spec*, not tested here. | Grant a folder in headful Chrome, reload, save again, confirm no dialog. |
| `queryPermission` returns `granted` on a later page load rather than re-prompting. | Same run: the second save should be silent. |
| The picker opens and bytes land on disk at all. Headless returns `AbortError` because there is no picker UI. | Open headful, click Save, `ls` the folder. |
- Because every `file://` page shares one `localStorage` origin, the storage key **must** be
  unique per review (`refinement:<slug>:v1`). A generic key would load a different document's
  answers into this form. This is why step 4 exists.
- No external hosts: the artifact CSP blocks every one, and a `file://` page has no server.
  No CDN, no fonts, no fetch. Everything inline.

## Writing decision cards

A card the reviewer cannot decide from without opening the source document has failed.

Each card carries exactly three things:

1. **Claim** — one line, present tense, stating what will be true if approved.
   "`X-Source-System` is the discriminator", not "Discriminator options".
2. **Detail** — the minimum needed to rule on it: the specific numbers, the names, the mechanism.
   Two short paragraphs at most.
3. **Why this matters** — the consequence of getting it wrong, or the thing that changed. This is
   what turns a shrug into a verdict.

Group cards under headings when the kinds differ (corrections / design / open items). Give every
card a short stable id (`D1`, `C2`, `O4`) — it is the join key in the result file.

## Common Pitfalls — STOP

- A result file that exists before the reviewer has opened the form
- Reading only the verdict and skipping the note
- Treating an item under `## Not answered` as agreement
- A storage key that isn't unique to this review
- A card whose detail is "see §4 of the design doc"
- An uncapped watch loop
- Claiming the save worked because the code path exists — the UI reports the outcome; believe the
  reported outcome, and if the reviewer says nothing, check the file

## Verification Checklist

- [ ] `CONFIG.storageKey` is unique to this review and does not retain the template example
- [ ] `CONFIG.outName` and `CONFIG.expectedDir` match the watch path
- [ ] No result file was pre-created and the watch has a finite stopping condition
- [ ] The saved result ends with `<!-- end refinement feedback -->`
- [ ] Every answered decision's verdict and complete note were read before reconciliation

## Files

- `references/form-template.html` — the generator template, parameterised by `DECISIONS`.
- `references/result-template.md` — the exact markdown shape the form emits, so the parser knows
  what to expect.