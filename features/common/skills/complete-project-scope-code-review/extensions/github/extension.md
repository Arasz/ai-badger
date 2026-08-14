# complete-project-scope-code-review extension: github

This is a **config-gated extension** of the base skill, not a standalone skill.

**Activates when:** `sourceControl.platform == "github"` and `sourceControl.repoUrl` is set.

## github: the campaign branch and its PR

A project-scope review produces one long-lived **campaign branch** off the default branch, with
each work package merged into it from its own lane branch. That shape — rather than one PR per
package straight to the default branch — is what makes the join review of Phase 7 possible: the
joins happen somewhere you control before anything reaches the trunk.

- Open the campaign PR as a **draft** as soon as the review document exists, so a human can watch
  it grow. Push after every commit.
- The version marker is bumped **once** for the campaign, not per wave, while nothing has been
  tagged. Maintain its release-notes entry as each wave merges — a wave that lands without
  amending the entry ships unrecorded under a number that claims to describe it.
- Never push to the default branch.

## github: integrating a base that moves under you

The default branch will move during a campaign this long. That is the single most productive
source of join defects, and it needs treating as a merge to review rather than a chore.

**Before judging any lane finding against a moved base:** re-fetch, and diff the reviewed head
against the merged commit. A squash-merge landing during the review can contain changes the lanes
never saw — the author may have pushed reworks between your dispatch and the merge — so a finding
citing `path:line` may cite a shape that no longer exists. Re-verify each surviving finding against
the merged file before accepting it.

**Resolving conflicts where the trunk refactored what your branch changed.** The recurring shape is
"main restructured the helper while this branch changed the behaviour underneath it". Take the
trunk's structure and splice your behaviour into it — but a wholesale take costs two things that
the build will not catch:

1. **Tests with no counterpart on the other side are dropped silently.** Enumerate them and restore
   them explicitly.
2. **Deliberately-changed constants are reverted.** An assertion your branch changed on purpose —
   an exit code, a threshold, a name — goes back to the trunk's value and nothing fails. Re-apply
   it with the reason on the line.

Diff each resolved file against **both** parents afterwards and account for every line that
disappeared. Then run the affected suites, not just the build.

## github: review rounds and merge

If the project uses an automated reviewer, run the campaign PR through it once per wave rather than
once at the end — a 40-file wave gets a useful review, a 400-file campaign does not. Triage a whole
review batch together before implementing, since findings interact, and verify each finding still
applies to the branch head before acting on it: review snapshots lag the commit they are tagged
against.

Reply on every thread you addressed, deferred to a filed issue, or determined stale, and resolve
it. A resolved-in-code thread left open is indistinguishable from an ignored one.

Squash-merge the campaign once a review round returns with no new findings since the last pushed
commit and the merged-tree gates are green.

## github: workflow findings the review should file

A project-scope review is the right moment to check the CI definition itself, because nothing else
ever does:

- Every third-party action pinned to a full commit SHA, never a tag.
- The workflow's test filters **partition** the suite — sum them and compare to the total run
  count. A test matching no filter is a test CI does not run, and it will look covered.
- Least-privilege `permissions` declared at the workflow or job level.
