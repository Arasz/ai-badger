# Research: keeping rtk-proxy installed across Homebrew upgrades

**Date:** 2026-10-18
**Question:** How do we make sure the `rtk-proxy` daemon binary is not removed when Homebrew upgrades `rtk`?

## Findings

### F1 — rtk-proxy was copied by hand into the Homebrew rtk keg; the formula never built it [MEASURED]
`/opt/homebrew/bin/rtk-proxy` is a symlink into `/opt/homebrew/Cellar/rtk/1.0.1/bin/rtk-proxy`. The keg's cargo metadata lists one binary (`.crates.toml`: `= ["rtk"]`, `.crates2.json`: `"bins":["rtk"]`). Its mtime is 2026-10-17 16:14, 27 minutes after the keg was poured (receipt `time` 1792244860 = 15:47), while `rtk` carries the bottle's 2026-10-14 mtime.
**Evidence:** `ls -la /opt/homebrew/bin/rtk-proxy`; `cat .../1.0.1/.crates.toml`; `grep -o '"bins":...' .../.crates2.json`; `stat -f '%Sm %N' .../bin/*`; `date -r 1792244860`. macOS arm64, Homebrew 7.0.9, rtk 1.0.1, 2026-10-18.

### F2 — the installed rtk comes from homebrew/core, not the rtk-ai/tap the docs name [MEASURED]
`INSTALL_RECEIPT.json` records `tap: homebrew/core`, `poured_from_bottle: true`. The core formula runs `cargo install *std_cargo_args` at the crate root, which builds only the `rtk` crate.
**Evidence:** `INSTALL_RECEIPT.json` `source.tap`; `/opt/homebrew/Cellar/rtk/1.0.1/.brew/rtk.rb` `def install`.

### F3 — neither Homebrew formula installs rtk-proxy [READ]
The core formula (F2) and the `rtk-ai/homebrew-tap` formula (`def install; bin.install "rtk"; end`) both ship `rtk` only. The proxy is a separate crate (`proxy/Cargo.toml`) and a separate release asset, `rtk-proxy-aarch64-apple-darwin.tar.gz`.
**Evidence:** `gh api repos/rtk-ai/homebrew-tap/contents/Formula/rtk.rb`; `gh release view v1.0.1 -R rtk-ai/rtk --json assets`; `rtk-ai/rtk` `proxy/README.md:57`.

### F4 — upstream's documented install is "next to rtk, or anywhere on PATH" [READ]
"`rtk` looks for the daemon next to its own binary first, then on `PATH`." The installation page (https://www.rtk-ai.app/docs/getting-started/installation/) does not mention the proxy at all.
**Evidence:** `rtk-ai/rtk` `docs/guide/proxy/overview.md:29-39`.

### F5 — brew upgrade removes the old keg, taking rtk-proxy with it [READ]
"Unless $HOMEBREW_NO_INSTALL_CLEANUP is set, brew cleanup will then be run for the upgraded formulae." Cleanup deletes the 1.0.1 keg, and the new 1.0.2 keg is built from the formula, so it has no rtk-proxy (F3).
**Evidence:** `man brew` (Homebrew 7.0.9), `upgrade` section, line 1883.

### F6 — after the upgrade, Claude Code fails on its next session, not straight away [INFERRED]
`~/.claude/settings.json` sets `ANTHROPIC_BASE_URL=http://127.0.0.1:8080`, and its SessionStart hook is `rtk hook claude`, which upstream says starts the daemon (overview.md:71). The running daemon (PID 93751, started 2026-10-17 17:16) keeps its unlinked inode and works until it exits. After that, nothing can find a binary to start, port 8080 is dead, and every API request fails. This rests on F5 plus the measured settings, `ps` output and the upstream hook description; I did not run an upgrade.

### F7 — `HOMEBREW_NO_INSTALL_CLEANUP` and `brew pin` do not fix this [INFERRED]
Without cleanup the old keg survives, but `brew upgrade` still unlinks it and links the new keg, so `/opt/homebrew/bin/rtk-proxy` disappears from PATH. Lookup "next to rtk" then looks in the new keg (F4) and finds nothing. `brew pin rtk` keeps the proxy only by freezing rtk at 1.0.1 (`brew pin --help`). This follows from F4 and F5 and from brew's unlink/link behaviour, which I did not test.

### F8 — two durable fixes: a PATH directory brew does not own, or a formula that installs the proxy [INFERRED]
(a) **Simplest:** extract the release asset into `~/.local/bin/rtk-proxy`, which is on PATH (measured `$PATH`), and delete the hand-placed keg copy and its symlink. Brew never writes there, and F4's PATH fallback finds it. Cost: the proxy is not upgraded alongside rtk, so you update it yourself when rtk moves.
(b) **Version-lockstep:** a personal tap formula `rtk-proxy` that `bin.install "rtk-proxy"` from the release tarball, with a pinned sha256. `brew upgrade` then manages it like any other formula. Cost: bumping url/sha for every release, or a livecheck.
Both follow from F3–F5. Neither was installed and exercised in this session.

### F9 — fix (a) applied; rtk now resolves the proxy from ~/.local/bin [MEASURED]
I downloaded the release asset, which matched its `checksums.txt` sha256 `3022be21…`. The extracted binary was byte-identical to the keg copy. I installed it to `~/.local/bin/rtk-proxy` and removed the keg copy and the `/opt/homebrew/bin` symlink. Afterwards `which -a rtk-proxy` shows only `~/.local/bin`, `brew list rtk` lists no proxy, `rtk llm-proxy setup` prints "binary ready: /Users/arasz/.local/bin/rtk-proxy", and `rtk llm-proxy status` reports "running at 127.0.0.1:8080 (v1.0.1)". `~/Library/LaunchAgents` has no rtk entry, so no service needed reinstalling.
**Evidence:** `gh release download v1.0.1 -R rtk-ai/rtk`; `shasum -a 256`; `install -m 755`; the commands quoted above. Run 2026-10-18.

### F10 — a restart starts the daemon from ~/.local/bin, and the session survives it [MEASURED]
Before the restart, PID 93751 still ran as `/opt/homebrew/bin/rtk-proxy start --bind 127.0.0.1:8080`: the path F9 deleted, kept alive by its unlinked inode. `rtk llm-proxy stop` followed by `rtk llm-proxy start` brought up PID 92443 at 13:01:31 as `/Users/arasz/.local/bin/rtk-proxy start --bind 127.0.0.1:8080`, and `rtk llm-proxy status` reported "running at 127.0.0.1:8080 (edition local, v1.0.1)". The Claude Code session whose `ANTHROPIC_BASE_URL` points at the proxy kept working across the restart: its next API request went through the new daemon. So F9's fix holds on a real start, not only in `setup`'s lookup.
**Evidence:** `ps -o pid,lstart,command` before and after; `rtk llm-proxy stop`, `start` and `status`, run in one detached `nohup sh -c`. Run 2026-10-18.

### F11 — `rtk pipeline validate` misreports the ai-badger guard as a missing hook [MEASURED]
`rtk pipeline validate` prints "pipeline: ok (haiku-compaction)" and then "hook needed: PreToolUse hook missing — … run `rtk init -g`". The PreToolUse Bash hook is present: `python3 -I …/features/common/tools/rtk/scripts/rtk_guard.py`, installed by 0.197.0. `rtk pipeline explain --agent claude-code --tool Bash` resolves `hook.before_tool.shell` to the rule `rtk-rewrite`, and Bash output in this session came back condensed. The validator apparently recognises only the literal `rtk hook` command. Following its advice would put back the plain rtk hook and lose the guard's ask-rule protection.
**Evidence:** `rtk pipeline validate`; `rtk pipeline status`; `rtk pipeline explain --agent claude-code --tool Bash`; the hook commands in `~/.claude/settings.json`. Run 2026-10-18.

## Still open

- **Not measured:** an actual `brew upgrade rtk` removing the proxy. F5–F7 are read or inferred. A safe repro is a throwaway `HOMEBREW_PREFIX`, not the live one, because the live daemon is fronting this session.
- **Unverified:** whether rtk's "next to its own binary" lookup resolves the `/opt/homebrew/bin/rtk` symlink (keg dir) or uses the link dir (`/opt/homebrew/bin`). If it is the link dir, a stale dangling symlink there matters too.
- **Unverified:** whether rtk-proxy 1.0.1 works with a newer rtk, i.e. how strict the skew between the two is under fix (a).
- **Unverified:** whether `rtk llm-proxy service install` (launchd) records an absolute path to the binary. If it does, moving the binary (fix a) means reinstalling the service.
- **Unverified:** whether upstream intends to add rtk-proxy to `rtk-ai/tap`. Filing an upstream issue would resolve it and would make fix (b) unnecessary.
- **Unverified:** how the proxy got into the keg on 2026-10-17. No record of it was found in `docs/work/2026-10-17-rtk-*`.
