# meta — machine state about the documentation itself

Indexes, baselines, ledgers and migration state: files a tool writes and a tool reads. Nothing
here is prose, and nothing here is edited by hand.

This framework's documentation machine state lives outside this directory today, because it
predates it: `../changelog/README.md` carries the generated changelog index
(`tooling/changelog_index.py --check` owns it) and `../../index.json` carries the catalog index
(`tooling/index_build.py --check` owns it). Both are pinned by gates and by `CLAUDE.md`, so
neither moves here without its own PR.

## Files

Empty.
