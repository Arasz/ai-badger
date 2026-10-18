<!-- rtk tool -->
## Tools: rtk

Shell commands may pass through rtk, which compresses their output; an `rtk`-prefixed command
means the same as the bare one. Verify it with `rtk gain` (savings counts), not `rtk init --show`:
rtk does not recognise ai-badger's guarded hook. Running `rtk init` for an agent ai-badger already
wires adds a duplicate hook, and an agent already wired user-level (`rtk init -g`, a global pi
extension) should not be opted in here.
- **Claude:** wired through a guard; a command a `permissions.ask` rule names runs unrewritten.
- **Codex:** not wired yet; rtk's own hook hides commands from Codex rules, approval and classifier.
- **Privacy:** rtk keeps every proxied command in a plaintext `history.db` for 90 days. Set
  `tracking.enabled=false`, move it with `RTK_DB_PATH`, or turn recall off with `RTK_RECALL=0`.
- **Licence:** the default build links BUSL-1.1 rtk-engine; Apache-2.0 `rtk-oss` is the alternative.
- **Trust:** the hook runs the first `rtk` on PATH with your shell's trust. POSIX shells only.
