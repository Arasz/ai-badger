<!-- rtk tool -->
## Tools: rtk

Shell commands may pass through rtk, which compresses their output; an `rtk`-prefixed command
means the same as the bare one. Verify it with `rtk gain` (savings counts), not `rtk init --show`:
rtk does not recognise ai-badger's guarded hook. Running `rtk init` for an agent ai-badger already
wires adds a duplicate hook, and an agent already wired user-level (`rtk init -g`, a global pi
extension) should not be opted in here.
- **Claude:** not wired; Claude checks `permissions.ask` against the rewrite, so ask rules lapse.
- **Codex:** rtk's hook always answers `allow`, so a rewritten command skips Codex's approval
  prompt and its safe/dangerous classifier.
- **Privacy:** rtk keeps every proxied command in a plaintext `history.db` for 90 days. Set
  `tracking.enabled=false`, move it with `RTK_DB_PATH`, or turn recall off with `RTK_RECALL=0`.
- **Licence:** the default build links BUSL-1.1 rtk-engine; Apache-2.0 `rtk-oss` is the alternative.
- **Trust:** the hook runs the first `rtk` on PATH with your shell's trust. POSIX shells only.
