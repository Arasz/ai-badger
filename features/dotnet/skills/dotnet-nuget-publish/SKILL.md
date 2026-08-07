---
name: dotnet-nuget-publish
description: Use when publishing a .NET package to nuget.org or its CI.
---

# dotnet-nuget-publish

Publish a .NET library or PackAsTool global tool to nuget.org behind secure, human-gated GitHub Actions.

## When to use
- "configure nuget publish" / "add publish workflow" / "publish the package"
- Writing or fixing `.github/workflows/*.yml` (build/publish/nightly/labeler)
- csproj pack metadata (`PackageTags`, license, authors, URLs)

## Design decisions
1. **Trusted Publishing (OIDC), not API keys.** The nuget.org policy is keyed to package owner + repo + **workflow file name only** (e.g. `publish.yml`) + optional GitHub environment. The workflow MUST match the policy exactly; if the policy says environment `production`, the push job must run under `environment: production`.
2. **Manual approval = environment with required reviewers.** Put ONLY the push job under the environment; build/pack jobs need no approval. The run pauses at the push job until a human clicks Approve (user preference: publishes are hand-approved).
3. **Version = csproj `PackageVersion`** (single source of truth; bump + merge before each dispatch). Without a bump a re-dispatch is a silent no-op (`--skip-duplicate`).

## Trusted Publishing essentials

- Policy is created on nuget.org: Account -> Trusted Publishing. Fields: Package
  Owner, Repository Owner, Repository, **Workflow File** (file name only, e.g.
  `publish.yml`), **Environment (optional)**.
- The workflow requests a short-lived key: `NuGet/login@v1` with `user:` =
  the nuget.org **profile name of the policy creator** (not the owner, not an
  email). Outputs `NUGET_API_KEY`; push with
  `dotnet nuget push ./artifacts/*.nupkg --api-key ${{ steps.login.outputs.NUGET_API_KEY }} --source https://api.nuget.org/v3/index.json`.
- Job needs `permissions: id-token: write` or the OIDC request silently fails.

## The environment-matching rule (the #1 failure mode)

The GitHub Actions **environment name carried in the OIDC token must EXACTLY
equal the policy's Environment field**. Any mismatch fails at the token exchange:

```
Token exchange failed (HTTP 401) ... Environment mismatch for policy 'Dotnet Ignore':
expected 'production', actual 'publish'
```

- The error message names both sides — read it as the ground truth; do not trust
  what the user thinks the policy says. When user intent and the live 401 disagree,
  the 401 wins (verified: user believed policy said `publish`; policy page and
  three live 401s said `production`).
- The policy page (nuget.org -> Trusted Publishing -> policy) is the authoritative
  source: it shows `Workflow: publish.yml Environment: production`.
- `NuGet/login@v1` also fails if `user:` is wrong ("use the username of the policy
  creator, not the policy owner").

## Approval gate: GitHub environment required reviewers

- `environment: <name>` on the job + a **required reviewer** rule on that
  environment pauses the run before ANY step; the run shows "Review deployments" ->
  "Approve and deploy" (reject fails the run). This is the standard manual gate.
- `required_reviewers` is **UI-only**: the REST API returns 404 for
  POST .../environments/{name}/protection-rules with type required_reviewers
  (verified twice). wait_timer/branch_policy rules are API-manageable; required
  reviewers are not. Tell the user: Settings -> Environments -> <name> ->
  Required reviewers.
- "Prevent self-approvals" on the environment blocks a sole owner from approving
  their own runs — leave it off for single-owner repos.

## Trigger choice: push to trunk, not pull_request (branch-policy trap)

A `pull_request`-triggered run executes from the PR **merge ref**
(`refs/pull/<n>/merge`). If the target environment has a branch policy, the run
is rejected:

```
Branch "refs/pull/15/merge" is not allowed to deploy to production due to
environment protection rules.
```

Fix: trigger on the trunk push — a merge to master IS a push, and the run's ref
is `refs/heads/master`, which branch policies allow:

```yaml
on:
  push:
    branches: [master]
  workflow_dispatch:
```

Consequence: every push to trunk creates a pending run; the approval gate is the
release control (approve, or ignore/cancel). Manual `workflow_dispatch` runs from
the default branch ref and also passes branch policies.

## Workflow skeleton (verified)
build.yml — on push/PR: checkout + setup-dotnet + `dotnet build` + fast tests only (`--filter "Speed=Fast"`); full suite moves to nightly.
publish.yml — `workflow_dispatch` restricted to `branches: [main]`:
- pack matrix, one job per RID:
  1. `mkdir -p .nupkg-local` (nuget.config local-feed reference → NU1301 on fresh runner)
  2. `dotnet build -c Release -p:RuntimeIdentifiers=${{ matrix.rid }}` — **build before pack** (packing an unbuilt multi-RID project fails MSB3030)
  3. `dotnet pack ... --no-build -o artifacts`
  4. upload-artifact
- publish job: `needs: pack`, `environment: production`, `permissions: {contents: read, id-token: write}`, download-artifact, `NuGet/login@v1` (`user: <nuget username>`), push all nupkgs with `--api-key ${{ steps.login.outputs.NUGET_API_KEY }} --source https://api.nuget.org/v3/index.json --skip-duplicate`.
nightly.yml — cron + `workflow_dispatch`, `concurrency: {group: nightly, cancel-in-progress: false}`, full `dotnet test`. Scheduled runs are best-effort (GitHub can drop/delay them); document `gh workflow run nightly.yml` for re-arming.

## PackAsTool: build before pack (MSB3030)

`dotnet pack -c Release` on a `PackAsTool` project **fails on a clean checkout**
with MSB3030 ("Could not copy the file bin/Release/net10.0/... because it was not
found") — the implicit build inside pack does not produce the publish-stage
outputs its own publish pass expects. Reproduced on a fresh clone; the workflow
must be:

```yaml
- name: Build
  run: dotnet build src/<Proj>.csproj -c Release
- name: Pack
  run: dotnet pack src/<Proj>.csproj -c Release --no-build -o ./artifacts
```

## PackAsTool multi-RID facts
- Pack emits a tool shell + per-RID payload packages; **both must be pushed** or `dotnet tool install` fails.
- All matrix jobs emit the same shell id+version → `--skip-duplicate` is required (jobs 2-6 become no-ops), not an optimization.
- Build before pack, or pack `--no-build` after a build — otherwise MSB3030 in Microsoft.NET.Publish.targets.

## Green publish run that published nothing (409 on every push)

With `--skip-duplicate` on the push, EVERY 409 conflict becomes a no-op and the run
still concludes **success** — a green run proves nothing was pushed. The push-step
lines are the truth: `PUT ... 201 Created` = published, `Conflict ... already exists` =
skipped. Always read them before telling anyone the release is live.

Diagnosis when every push 409s for a version the read APIs can't see (full ladder in
`references/push-409-invisible-package.md`):

1. **Read-API sweep** — flat container `https://api.nuget.org/v3-flatcontainer/<id>/index.json`
   (404 = no versions AT ALL, listed or unlisted), registration
   `.../v3/registration5-gz-semver2/<id>/index.json` (XML BlobNotFound), search
   `https://azuresearch-usnc.nuget.org/query?q=packageid:<id>&prerelease=true` (totalHits 0),
   gallery page 404. All four invisible = the id exists nowhere public.
2. **Control the queries** — query a known-live package owned by the SAME account
   (e.g. a sibling tool). If it shows up in all four, your queries are sound AND the
   account's OIDC publishing mechanism works — the problem is specific to this id/version.
3. **Check earlier runs** — `gh run list --workflow publish.yml` + `gh run view <n> --log |
   grep -E "Pushing|PUT http|Conflict|Created"`. An older run that ALSO all-conflicted on
   an earlier version means the block predates the current bump; the login step saying
   "Successfully exchanged OIDC token" rules out a policy problem.
4. **Official docs rule out "deleted"** — nuget.org does NOT support permanent deletion,
   only unlisting, and unlisted versions STAY in the flat container.

## Version bumps: pin-sync + RED-first

A release bump touches FOUR files, and the contract test goes RED first:

1. `tests/.../Unit/Setup/VersionContractTests.cs` — the `ExpectedVersion` const.
   Change it FIRST and run the test: two facts fail (csproj and server.json
   mismatch). Capture the RED output in the commit message; bumping the csproj
   before the test is a TDD violation.
2. `src/<pkg>/<pkg>.csproj` — `PackageVersion`, `InformationalVersion`,
   AND `AssemblyVersion` (all three; MCP `serverInfo.version` reads
   AssemblyVersion, `--version` reads InformationalVersion — both must carry the
   real numeric version, no prerelease suffix).
3. `src/<pkg>/.mcp/server.json` — `version` AND `packages[0].version`.
4. The fresh-install test script — the docstring pin AND the default
   `VERSION = os.environ.get("<PKG>_VERSION", "<prev>")`. Both go stale every
   release; the default must equal the new version or the post-publish run tests
   the WRONG version unless a human remembers the env var. The script's own
   header says "pin must be bumped after each republish — NuGet versions are
   immutable".

## Pre-publish verification of a tool package (nuget.org doesn't have it yet)

The fresh-install script proves a CLEAN INSTALL from nuget.org — impossible
before the version is published. Dress-rehearse it pre-merge with a locally
packed nupkg:

- `dotnet tool install --tool-path <tmp> --add-source <packdir> --version <V> <pkg-id>`
  works against a folder source and exercises the same shell+payload shape,
  store layout, native libs, and sha256 pins as the real install.
- If the repo already has a local-pack target (a `DeployToLocalSource`-style
  target triggered by an env-var build → `.nupkg-local`), point `--add-source`
  at it — don't invent a second pack path.
- Give the fresh-install script an env switch (`<PKG>_SOURCE=local|nuget`,
  default nuget) so the SAME script is the pre-merge gate (local) and the
  post-publish gate (nuget.org); document the split in the review record.
- Pitfalls: a gitignored model bundle means a fresh checkout packs WITHOUT
  `Models/` and the sha256 step FAILS LOUDLY (correct behavior — run the
  model-download script first, exactly as publish.yml does). A local pack
  carries only the host RID in its shell (fine locally); if `--add-source`
  resolution mis-picks the package, install the RID-scoped nupkg by exact
  filename (`<pkg-id>.<rid>.<V>.nupkg`). Local runs must keep the script's
  `--tool-path` isolation — never touch the shared `~/.dotnet/tools` store (a
  prior incident: a missing native asset in the shared store broke the app for
  every session).

## Metadata checklist (NuGet package-authoring best practices)
- `PackageLicenseExpression` (SPDX/OSI-approved; match the repo LICENSE — missing license = legal default to exclusive copyright)
- `Authors` = pretty name (NOT the username), `Copyright`
- `PackageProjectUrl`, `RepositoryUrl` + `RepositoryType=git`
- `PackageReadmeFile`, `PackageReleaseNotes` (URL link is acceptable)
- `Description` = what it is; it is the first line of search results
- `PackageTags` = **terms a user would type to find the tool — never internal features** (no observability/sync/encryption/implementation details). Space-delimited, <4000 chars.
- Icon: optional (doc says CONSIDER); skip when no asset exists.

## Pitfalls (all hit in the wild)
- **Action versions go stale.** Verify each against `gh api repos/{owner}/{repo}/releases/latest --jq .tag_name`; pin the major. 2026-08 snapshot: checkout@v7, setup-dotnet@v6, upload-artifact@v7, download-artifact@v8, NuGet/login@v1, labeler@v7, github-script@v9.
- **NU1301** — nuget.config `<clear/>` + local folder source fails restore when the gitignored dir is absent on a fresh runner. `mkdir -p` it before restore.
- **Case-sensitivity**: macOS dev (case-insensitive FS) hides path-case bugs that fail Linux runners (MSB3030 on Content Include, stale gitignore paths, directory-walk resolvers). Use the real dir case (`Unit/Retrieval`, not `unit/retrieval`).
- **Gitignore drift**: ignore paths that don't match the real dir commit binaries despite the ignore intent. Fix paths + `git rm --cached`.
- **Hardcoded platform binaries in test harnesses**: macOS-only `.dylib` pins break Linux. Manifest per-platform entries (osx-arm64 `.dylib`, linux-x64 `.so`), resolve CurrentPlatform from `RuntimeInformation`, bootstrap per platform; keep platform-independent assets untagged.
- **xunit parallel races on shared globals**: two classes attaching ActivityListeners to one global ActivitySource race (a sibling's activity clobbers the captured reference — flaky 2/5 runs, green in isolation). Serialize via `[Collection(name)]` with `DisableParallelization = true`.
- **Post-push indexing lag (measured 2026-08)**: right after a push, the FLAT CONTAINER serves every nupkg but the RID payload REGISTRATIONS can lag ~15-20 min (shell registers immediately; `registration5-gz-semver2/<id>.<rid>/index.json` 404s, search shows 0 hits). `dotnet tool install` fails in that window with "Version X of package <id>.<rid> is not found" despite the blobs existing — a FALSE alarm, not a broken publish. Gate the fresh-install script on the payload registration returning 200 first.
- **Post-publish fresh-install false-fail: the NuGet http-cache + registration lag.** Right after a publish, `dotnet tool install --version <V>` can fail with "Version <V> of package <id> is not found in NuGet feeds" even though the package IS live. Two compounding causes (verified 2026-08): (a) the flatcontainer nupkg blob goes HTTP 200 within minutes, but dotnet resolves tool versions via the REGISTRATION endpoints (`registration5-semver1` / `registration5-gz-semver2`), which lag minutes-to-hours longer — check those, not just the flatcontainer, before declaring the push failed; (b) the user-level NuGet HTTP cache at `~/.local/share/NuGet/http-cache` stores the stale registration and dotnet serves it (the `-v d` install log shows `CACHE https://api.nuget.org/v3/registration5-gz-semver2/...`). Fix: `rm -rf ~/.local/share/NuGet/http-cache` and re-run. NOTE the cache dir is `http-cache`, NOT `v3-cache` (clearing the wrong dir does nothing — a wasted cycle). The fresh-install script should clear this cache in its isolation preamble; the flatcontainer check (`curl .../index.json | tail`) alone is NOT proof of installability.
- **Clean-main reproduction for gate failures.** If a post-merge full suite shows failures in tests your PR didn't touch (retrieval gates, baselines, corpus-dependent asserts), verify they fail on a CLEAN checkout of origin/main (or a scratch worktree at the base commit) BEFORE treating them as your regression. Corpus/fixture drift (a backfilled corpus DB without updated gate baselines) produces exactly this: gate tests fail identically on main, unrelated to your change. Record the finding and report the classification — don't chase a fix that belongs to the corpus-owning workstream.

## Verify
- `dotnet build` 0 warnings; fast filter green; full suite green
- YAML parses (note: PyYAML is YAML 1.1 and coerces the `on:` trigger key to boolean True — access via `doc.get("on", doc.get(True))`)
- `dotnet pack` then unzip the nuspec: tags, license, repository, authors present
- nuget.org policy page matches workflow file name + environment
