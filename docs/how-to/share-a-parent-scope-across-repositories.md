# Share one ai-badger scope across several repositories

Use this when a group of repositories should share one instruction and skill catalog, while
each repository keeps its own identity, state and authored settings. A collection holds a
parent `.ai-badger/` directory; the repositories inside it are the members.

The parent carries the union of the members' technology stacks. Every member is scaffolded
from that union, so a Python member and a .NET member both see the instructions and skills
of both stacks. The files that can safely be shared are shared as links; everything that
changes per repository stays local.

## Know what you need before you start

Each member must already be a scaffolded repository: a git checkout with its own
`.ai-badger/config.json` and its own `project-id`. The collection root is a directory that
holds the members; it is independent of where the framework lives, so a collection can sit
anywhere on disk, including outside the framework checkout.

That rule belongs to the explicit path, `collect`. The parent-side path (`init`, below) does
not need it: it scaffolds a member that has nothing yet, and converts one that already has
ai-badger.

Set `AI_BADGER` to the framework checkout that owns the script:

```bash
export AI_BADGER=/path/to/ai-badger
```

A Claude Code plugin install carries the same script under its own
`skills/welcome-ai-badger/scripts/` directory, so a plugin-only machine can call that copy
instead.

Members are named by their path relative to the collection root. The explicit path never
discovers neighbouring repositories on its own, and a path that escapes the collection is
refused. The parent-side path below does discover them, one level deep.

## Start from the parent side

When the collection is a directory of repositories you have not picked by hand, start from
the parent. `discover` shows you what is there, and `init` does the work:

```bash
python3 "$AI_BADGER/features/common/skills/welcome-ai-badger/scripts/shared_scope.py" discover \
  --target /path/to/source --root "$AI_BADGER"
```

```
member dotnet-app:dotnet
member python-app:python
union dotnet,python
```

One line per repository, `dir:stacks`, and the union of the stacks. Discovery is one level
deep: a repository inside another one is not a member, and nothing is written.

```bash
python3 "$AI_BADGER/features/common/skills/welcome-ai-badger/scripts/shared_scope.py" init \
  --target /path/to/source --root "$AI_BADGER"
```

`init` discovers the same repositories, then decides everything before it writes anything:
each member's identity, and each member's own settings. It then scaffolds the parent with
the union of the stacks and materializes every member from it. A member that has no
ai-badger yet is scaffolded; a member that already has one is converted — its own stacks
stay its own, its own settings become its overrides, and its own project id survives.

Use `--dry-run` first when the directory holds many repositories: it reports the members,
the union and every identity decision, and writes nothing.

```bash
python3 "$AI_BADGER/features/common/skills/welcome-ai-badger/scripts/shared_scope.py" init \
  --target /path/to/source --dry-run --root "$AI_BADGER"
```

`init` enrolls every repository it finds next to the target, so it is the wrong tool for a
directory that holds repositories meant to stay outside the scope; `collect` is the explicit
path. The `dir:stacks` index is kept in the parent's `.ai-badger/shared-scope.json` as
`memberStacks`.

## Enroll the members

```bash
python3 "$AI_BADGER/features/common/skills/welcome-ai-badger/scripts/shared_scope.py" collect \
  --target /path/to/collection --repo python-app --repo dotnet-app --root "$AI_BADGER"
```

`collect` does four things in order. It reads each member's own settings, computes the
union of the members' stacks, scaffolds the parent with that union, and materializes every
member from the same parent.

The parent takes its defaults from the collection's own `.ai-badger/config.json` when it
has one. To author them instead of editing that file afterwards, pass them in:

```bash
python3 "$AI_BADGER/features/common/skills/welcome-ai-badger/scripts/shared_scope.py" collect \
  --target /path/to/collection --repo python-app --repo dotnet-app \
  --config /path/to/parent-config.json --root "$AI_BADGER"
```

## Read what each member ended up with

Two files in a member describe it, and they answer different questions.

`.ai-badger/shared-scope.json` holds the member's authored settings: the stacks it had
before it was enrolled, and the overrides it wants on top of the parent's defaults. Edit
this file to change one member's behaviour.

`.ai-badger/config.json` holds the effective profile, which is what the agent reads. It is
generated, so do not edit it; a refresh replaces it.

The parent's files that are byte-identical to a member's are linked back to the parent, and
every link the shared scope owns is recorded in the member's `manifest.json`. The parent
keeps the real file, the member gets a relative symlink, and nothing else moves.

## Change the parent's defaults

Edit the parent's config and re-run `collect`. Objects merge, so a new command reaches the
members. Lists replace, so a member's own list wins over the parent's, and a parent list
change does not override a member that set its own.

A member that wants something different from the parent records it in its own
`shared-scope.json` overrides. Those survive every refresh.

## Refresh one member

```bash
python3 "$AI_BADGER/features/common/skills/welcome-ai-badger/scripts/shared_scope.py" sync \
  --target /path/to/collection/python-app --source /path/to/collection/.ai-badger --root "$AI_BADGER"
```

`sync` re-materializes one member and touches neither the parent nor the other members. It
renders that member with its own local stacks, so it is the command for a member that
should stand on its own.

Ordinary `scaffold.py` and `den-refresh` refuse a member that is enrolled. The refusal
names the command that restores it: `collect` for a member that carries the union, `sync`
for one that carries its own stacks. Follow the command it prints rather than guessing.

## Remove a member

```bash
python3 "$AI_BADGER/features/common/skills/welcome-ai-badger/scripts/shared_scope.py" prune \
  --target /path/to/collection --repo dotnet-app --root "$AI_BADGER"
```

`prune` detaches the member's shared files into private copies, leaves its identity alone,
shrinks the parent's union to the remaining members, and returns the member to the ordinary
scaffold and refresh flow. A collection keeps at least one member, so the last one cannot
be pruned.

## Identity

A member keeps the identity it already had. The shared scope never rewrites a
`project-id`, so the memory bank keeps seeing each repository under the id it registered
with.

A member with no id of its own gets one through the canonical ai-raccoon lookup. The bank's
id for that name is reused when the bank knows it, a name the bank does not know gets a
local id, and an answer the shared scope cannot trust stops the enrollment before anything
is written.

Nothing is registered with the bank unless you ask for it. Pass `--register` to `collect`,
`sync` or `prune` when a newly minted id should be registered too.

## Check the result

A member is enrolled when it has a `shared-scope.json` and the parent's `shared-scope.json`
lists it:

```bash
cat /path/to/collection/.ai-badger/shared-scope.json
```

Its identity, its state and its runtime stay its own. A nested working directory inside the
member resolves the member's id, not the parent's and not a sibling's.

## What the shared scope refuses

- A member path that escapes the collection, duplicates another member, is not a repository,
  or borrows another repository's `.ai-badger` directory.
- A member that is already enrolled in another collection, because two collections each
  claiming the same repository is a mess neither can repair.
- A link whose target no longer sits inside the parent, or whose recorded ownership no
  longer matches what is on disk. A link that was replaced by an ordinary file names the
  two ways out: delete the file and sync again, or prune the member out of the collection.

The decision records for the design are
[ADR-0041](../adr/0041-shared-parent-scopes.md) for the explicit path and
[ADR-0042](../adr/0042-parent-side-collection-initialization.md) for the parent-side one.
The commands and their flags are listed in [scripts.md](../scripts.md).
