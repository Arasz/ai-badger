# Never hand-edit the git directory

A hand-edited `.git/config` — a text editor, a shell redirect, a `sed -i` — rewrites the whole
file, so one mistake discards every section it did not reproduce: a rewrite that trimmed the
file to 296 bytes lost `remote.origin.fetch` and nearly every `[branch]` tracking section, and
the loss stayed silent — `git fetch origin` reports success and exits 0 while
`refs/remotes/origin/*` quietly stops moving, freezing `origin/main` at whatever commit it held
when the file broke, so every later comparison against it answers about a snapshot instead of
the remote. Write through git's own commands instead — `git config`, `git remote`,
`git branch --set-upstream-to` — each takes the config's lock file and rewrites only the key it
was given, never the sections around it. `git config --edit` is not a safe alternative: it opens
the identical raw file in your editor, so a bad save trims it the same way a hand rewrite does.
Nothing under a git directory is a text file you edit; it is a database git owns, and the only
writer that is allowed to touch it is git itself.
