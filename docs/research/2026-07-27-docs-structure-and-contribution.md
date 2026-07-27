# Research: documentation structure, OSS docs, contribution enforcement

**Date:** 2026-07-27
**Purpose:** input to the documentation refactor (see the "docs refactor" wave in
`docs/plans/2026-07-27-deferred-work-plan.md`). Gathered by web research; every factual claim
carries a source, and the researcher's own opinions are marked "(judgement)".

---

## 1. Directory structure patterns

### Findings

- **Diátaxis** organises docs on two axes — action vs. cognition, study vs. work — giving four
  quadrants: tutorials (learning, practical), how-to guides (task, practical), reference
  (information, theoretical), explanation (understanding, theoretical). It is explicitly
  pragmatic: "you don't have to believe in it" — a lens for iterative improvement, not a rigid
  schema. <https://diataxis.fr/start-here/>
- The closest sourced critique found is a practitioner report that applying it literally to
  *support* content blurred the quadrant boundaries and needed adapting.
  (judgement: for a small tooling repo, Diátaxis works better as a checklist than as four
  literal top-level directories — most small projects lack the content to fill them.)
  <https://contentbymfe.com/help-center/adapting-diataxis-for-support-content/>
- **ADRs**: convention is `docs/adr/` (or `docs/decisions/`), one file per decision,
  sequentially numbered, kebab-case imperative filenames (`0001-use-markdown-adrs.md`), **never
  edited after acceptance** — only superseded by a new ADR. MADR is the dominant Markdown
  template (title, status, context, decision, consequences).
  <https://adr.github.io/>, <https://adr.github.io/madr/>
- **Rust's RFC process** is ADR-at-scale: a dedicated repo, `text/` of numbered accepted RFCs,
  decisions via a "final comment period". Overkill for a small repo; the numbering and
  one-file-per-decision lesson is the transferable part. <https://rust-lang.github.io/rfcs/0002-rfc-process.html>
- **Changelogs**: "Keep a Changelog" is the dominant single-file convention — reverse
  chronological, one section per version, categorised (Added/Changed/Fixed/Deprecated/Removed/
  Security), `[Unreleased]` at the top. A committed `CHANGELOG.md` is recommended over GitHub
  Releases alone because Releases aren't versioned with the code.
  <https://keepachangelog.com/en/1.1.0/>
- Per-version changelog *files* (this repo's `docs/changelog/{version}-{slug}.md`) are a real
  but **minority** convention; the cited use case is "when changelog detail is vast and a single
  file becomes unwieldy" (e.g. Ruby's per-minor NEWS files).
  (judgement: per-file changelogs solve a *merge-conflict* problem — many contributors editing
  one growing file collide constantly — at the cost of needing an index to reconstruct the
  timeline. Worth it once concurrent contribution makes lock-step edits painful, not before.)
  <https://openchangelog.com/blog/changelog-md>
- At scale, changelogs are generated from Conventional Commits via **release-please** (Google)
  or **Changesets**. <https://github.com/googleapis/release-please/blob/main/docs/customizing.md>
- **GitHub's special-file resolution**: community-health files (README, CONTRIBUTING,
  CODE_OF_CONDUCT, SECURITY, SUPPORT, GOVERNANCE, FUNDING) are looked up in **repo root →
  `.github/` → `docs/`**, in that precedence. A file in any of the three is surfaced identically
  in GitHub's UI. <https://github.com/joelparkerhenderson/github-special-files-and-paths>
- **LICENSE must be at repo root** (GitHub only auto-detects it there). README is conventionally
  root (it renders on the repo homepage). Everything else is a placement choice.
- CNCF publishes ready-made templates for CONTRIBUTING, GOVERNANCE, CODE_OF_CONDUCT,
  MAINTAINERS, CONTRIBUTOR_LADDER, scaled to three governance shapes by project size.
  <https://contribute.cncf.io/maintainers/templates/>
- Kubernetes puts community/governance docs in a *separate* repo — a pattern only justified at
  very large multi-repo scale. <https://github.com/kubernetes/community>
- **Docs-as-code** (Write the Docs): docs in-repo, in Markdown, reviewed through the same PR
  flow as code. This is the assumption behind everything above.
  <https://www.writethedocs.org/guide/index.html>

### Recommended tree

```
README.md                      # what/why/quickstart — first contact, stays at root
LICENSE                        # root only — required for GitHub license detection
CONTRIBUTING.md                # root or .github/ — GitHub auto-surfaces either
SECURITY.md                    # root or .github/ — enables "Report a vulnerability" tab
CODE_OF_CONDUCT.md             # root or .github/
CHANGELOG.md                   # root, Keep-a-Changelog; OR docs/changelog/ for per-version files
VERSION                        # when version is tracked as a file (as here)

.github/
  ISSUE_TEMPLATE/
    bug_report.yml
    feature_request.yml
    config.yml                 # disable blank issues / link to Discussions
  pull_request_template.md
  CODEOWNERS
  dependabot.yml
  workflows/
    ci.yml
    docs-lint.yml              # Vale + markdownlint + lychee
    release.yml                # release-please / changesets

docs/
  tutorials/                   # Diátaxis: learning-oriented
  how-to/                      # Diátaxis: task-oriented recipes
  reference/                   # Diátaxis: authoritative facts (CLI flags, schema)
  explanation/                 # Diátaxis: design rationale
  adr/                         # 0001-title.md ... never edited post-acceptance
  changelog/                   # only if per-version files are chosen
    README.md                  # index reconstructing the release timeline
  plans/                       # working documents — not authoritative once merged
  reviews/                     # point-in-time audits / incident reports, dated
```

(judgement) Create Diátaxis's four folders literally only once `docs/` is too large to scan
flat; before that, a well-organised `docs/README.md` index applying the same four-way mental
model costs less than four half-empty directories.

---

## 2. What to document

### Minimum viable set

| Document | Purpose | Lives where | Required? |
|---|---|---|---|
| README.md | What it does, why, quickstart | root | Yes — first contact |
| LICENSE | Legal permission | root only | Yes — GitHub detection needs root |
| CONTRIBUTING.md | Issues/PRs, setup, expectations, tone | root or `.github/` | Yes, if accepting contributions |
| CODE_OF_CONDUCT.md | Behavioural norms | root or `.github/` | Strongly recommended |
| SECURITY.md | Private vulnerability reporting | root or `.github/` | Recommended; required by OpenSSF Best Practices Badge |
| CHANGELOG.md or docs/changelog/ | What changed per release | root or `docs/changelog/` | Recommended; mandated by this repo's own CLAUDE.md |
| GOVERNANCE.md | Who decides, how maintainers are added | root or `docs/` | Optional at 1–2 maintainers |
| ADRs | Why an architectural choice was made | `docs/adr/` | Optional, high-leverage |

<https://opensource.guide/starting-a-project/>, <https://www.bestpractices.dev/en/criteria/0>

### Keeping docs in sync

- **Docs-as-code** — docs in-repo, reviewed via normal PRs. <https://www.writethedocs.org/guide/index.html>
- **Prose linting** — **Vale**, rule-based, built for docs-as-code. <https://vale.sh/>
- **Markdown structure** — **markdownlint**, usually in the same CI job as Vale.
- **Link checking** — **lychee** (`lycheeverse/lychee-action`) to catch dead links pre-merge.
- **Doc ownership** — `CODEOWNERS` entries scoping `docs/` so doc changes route to a reviewer.
- **Pre-commit hooks** — the same checks locally; cited as the single biggest factor in whether
  writers internalise style rules rather than treating CI as an obstacle.
  <https://buildwithfern.com/post/docs-linting-guide>
- **Generated reference docs** — machine-generate CLI/API reference from source rather than
  hand-duplicating; the strongest anti-rot mechanism for the reference quadrant. (judgement)
- **"Docs required" PR gates** — not found as a named, sourced pattern; the practical equivalent
  is CI-enforced doc checks as *required status checks*.

---

## 3. Contribution guides and enforcement

### CONTRIBUTING.md contents

- How to report bugs / request features (often just points at issue templates)
- Environment setup and how to run tests locally
- The workflow (fork/branch, commit conventions, PR expectations)
- What contributions are wanted, and what is out of scope
- An explicit welcome to first-timers — a cold, legalistic doc measurably suppresses first PRs
- A link *from* the README, so it is discovered

<https://opensource.guide/starting-a-project/>, <https://contribute.cncf.io/maintainers/templates/>

### GitHub-native enforcement (config, no code)

- **Issue Forms** (`.github/ISSUE_TEMPLATE/*.yml`) — structured forms instead of free text.
  <https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms>
- **`pull_request_template.md`** — auto-populates every PR body.
- **CODEOWNERS** — forces review on paths like workflows or security policy.
- **Branch protection / rulesets** — required reviews, required status checks, no force-push.
  Rulesets (2023+) are the newer, stackable replacement for classic branch protection.
- **`.github/dependabot.yml`** — automated dependency PRs.
- **DCO vs CLA** — DCO is a per-commit `git commit -s` sign-off, no separate legal document
  (Linux kernel, GitLab, most CNCF projects). CLA is a one-time signed agreement, heavier
  (Apache, Google, Meta, HashiCorp, Kubernetes). DCO is the norm for small projects; CLA is for
  orgs needing IP assignment or relicensing flexibility.
  <https://www.secondstate.io/articles/dco/>, <https://opensource.com/article/19/2/cla-problems>
- **SECURITY.md + private vulnerability reporting** — powers GitHub's "Report a vulnerability"
  tab; required for the OpenSSF Best Practices Badge.
- **GitHub Discussions** — redirect non-bug chatter via `ISSUE_TEMPLATE/config.yml`.

### Action-based enforcement

- **`amannn/action-semantic-pull-request`** — enforces Conventional-Commits PR titles.
- **release-please** — parses Conventional Commits, opens a release PR with version bump +
  generated changelog.
- **Changesets** — contributors add a changeset file per PR; aggregated at release time.
- **Stale bots** — widely used and genuinely controversial: the sourced criticism is that they
  close PRs "due to perceived inactivity rather than actual human review".
  <https://jacobtomlinson.dev/posts/2024/most-stale-bots-are-anti-user-and-anti-contributor-but-they-dont-have-to-be/>
- **First-interaction greeting bots** — auto-welcome first-time contributors.
- **Vale/markdownlint/lychee in CI** — doubles as contribution enforcement: docs PRs face the
  same gate as code PRs.

### Worth it for a 1–2 maintainer project?

| Mechanism | Value | Cost | Verdict |
|---|---|---|---|
| README + LICENSE + CONTRIBUTING + CODE_OF_CONDUCT | High — baseline credibility | Very low, one-time | **Do it** |
| SECURITY.md + private reporting | High — responsible disclosure, no downside | Very low | **Do it** |
| Issue Forms (`.yml`) | Medium — better reports, less back-and-forth | Low | **Do it** |
| PR template | Medium — nudges self-check | Very low | **Do it** |
| CODEOWNERS | Low–Medium solo (you review everything anyway) | Very low | Only for sensitive paths (workflows, security) |
| Branch protection (CI green, no force-push) | Medium — cheap insurance | Very low | **Do it**, but skip approval-count gates — sourced guidance says 2-approval rules "slow down teams under 10 engineers with no measurable quality gain" (<https://www.arnica.io/blog/what-every-developer-needs-to-know-about-github-branch-protection>) |
| Vale + markdownlint + lychee in CI | Medium — real doc-rot prevention | Low | **Do it** — directly serves the docs-sync goal |
| DCO sign-off | Low–Medium — matters if outside contributions arrive | Very low | Adopt DCO, **skip CLA** |
| release-please / Changesets | Medium — removes changelog/bump toil | Medium; changes commit discipline | Worth it if releases are frequent; the manual VERSION+changelog flow here is simpler otherwise (judgement) |
| Semantic PR title check | Low | Very low | Only if release-please/Changesets need parseable titles |
| Stale bot | Low, real contributor-relations risk | Ongoing complaint handling | **Skip**, or comment-only with a long timeout |
| First-interaction bot | Low | Very low | Optional |
| GOVERNANCE.md | Very low at 1–2 maintainers | Adds ceremony | **Skip** until a second org joins |
| CLA | Low–Negative — suppresses casual contributions | High (legal + bot infra) | **Skip** |
| ADRs | Medium–High — prevents re-litigating decisions | Very low | **Do it** |

---

## 4. Top 10 recommendations, ranked

1. Keep README + LICENSE at root; let CONTRIBUTING/SECURITY/CODE_OF_CONDUCT live in `.github/`
   to keep root minimal — GitHub resolves all three locations identically, so choose on
   root-clutter tolerance, not tooling constraints.
2. Add `SECURITY.md` with private vulnerability reporting enabled — near-zero cost, required by
   the OpenSSF badge, and the most commonly missing "minimum viable" document.
3. Treat Diátaxis as a content checklist, not four mandatory folders — splitting a small `docs/`
   into four half-empty directories fragments it.
4. Put ADRs in `docs/adr/`, numbered, never edited post-acceptance — the cheapest high-leverage
   practice in this research.
5. Choose root `CHANGELOG.md` vs. per-version `docs/changelog/` on contributor concurrency, not
   aesthetics — per-file exists to avoid merge conflicts on one growing file.
6. Add Vale + markdownlint + lychee as CI checks on `docs/**` — the most concrete
   "keep docs in sync" lever available.
7. Enable branch-protection rulesets requiring CI green and no force-push to main; skip
   multi-approval gates at 1–2 maintainers.
8. Adopt DCO if external contributions are wanted; do not adopt a CLA.
9. Skip stale-bot auto-closing; comment-only with a long timeout if used at all.
10. Defer GOVERNANCE.md and CODEOWNERS review-routing until a second maintainer or org joins.

---

## Sources

<https://diataxis.fr/> · <https://diataxis.fr/start-here/> · <https://diataxis.fr/how-to-use-diataxis/> ·
<https://contentbymfe.com/help-center/adapting-diataxis-for-support-content/> ·
<https://idratherbewriting.com/blog/what-is-diataxis-documentation-framework> ·
<https://www.writethedocs.org/guide/index.html> ·
<https://www.writethedocs.org/guide/writing/beginners-guide-to-docs/> ·
<https://google.github.io/styleguide/docguide/best_practices.html> ·
<https://adr.github.io/> · <https://adr.github.io/madr/> ·
<https://github.com/architecture-decision-record/architecture-decision-record> ·
<https://ozimmer.ch/practices/2021/04/23/AnyDecisionRecords.html> ·
<https://rust-lang.github.io/rfcs/0002-rfc-process.html> · <https://github.com/rust-lang/rfcs> ·
<https://keepachangelog.com/en/1.1.0/> · <https://common-changelog.org/> ·
<https://openchangelog.com/blog/changelog-md> ·
<https://www.cloudbees.com/blog/appy-changelog-best-practices-development> ·
<https://github.com/googleapis/release-please/blob/main/docs/customizing.md> ·
<https://github.com/joelparkerhenderson/github-special-files-and-paths> ·
<https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests> ·
<https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms> ·
<https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/creating-a-pull-request-template-for-your-repository> ·
<https://opensource.guide/starting-a-project/> ·
<https://github.com/ossf/scorecard/blob/main/docs/checks.md> ·
<https://www.bestpractices.dev/en/criteria/0> · <https://scorecard.dev/> ·
<https://contribute.cncf.io/maintainers/templates/> ·
<https://github.com/cncf/project-template/blob/main/GOVERNANCE.md> ·
<https://github.com/kubernetes/community> · <https://kubernetes.io/docs/contribute/participate/> ·
<https://github.com/amannn/action-semantic-pull-request> ·
<https://www.secondstate.io/articles/dco/> · <https://opensource.com/article/19/2/cla-problems> ·
<https://osr.finos.org/docs/bok/artifacts/clas-and-dcos> ·
<https://vale.sh/> · <https://buildwithfern.com/post/docs-linting-guide> ·
<https://earthly.dev/blog/markdown-lint/> ·
<https://docs.gitlab.com/development/documentation/testing/vale/> ·
<https://jacobtomlinson.dev/posts/2024/most-stale-bots-are-anti-user-and-anti-contributor-but-they-dont-have-to-be/> ·
<https://github.com/probot/stale> ·
<https://www.arnica.io/blog/what-every-developer-needs-to-know-about-github-branch-protection> ·
<https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches> ·
<https://how2.sh/posts/how-to-build-branch-protection-policies-for-engineering-teams/> ·
<https://github.com/pnpm/pnpm/blob/main/CONTRIBUTING.md> ·
<https://github.com/colinhacks/zod/blob/main/CONTRIBUTING.md>
