# Owner-gate reconciliation — message-bus QA follow-ups

**Date:** 2026-09-01 · **Form:** `2026-09-01-bus-qa-followups-owner-gate.html` · **Feedback:** `2026-09-01-bus-qa-followups-feedback.md` (7/7 answered, end marker verified)
**Source findings:** `.ai-badger/task-tracking/plans/2026-09-01-aib-user-db-message-bus-qa-review.md` (M2, L1, L2, L4/L5, L6, L8, L9)

## Final rulings

| Card | Finding | Ruling | What it means |
|---|---|---|---|
| D1 | M2 — one family's resurrection bricks `open_user` for all families | **APPROVE (c)** | Per-family containment in `_open` (a resurrected family degrades that family, not the store) **+** doctor/den-refresh detect-and-repair path. Owner asked what "family" means — answered (legacy-file ↔ sqlite-table mapping, `badger_store.py:519–580`); ruling stands. |
| D2 | L1 — gated first read cursor overshoot consumes unresolved-project mail | **CHANGE — widened by owner** | Owner rejected the raccoon-bank dependency outright: **ai-badger must be independent. New rule: where there is `.ai-badger`, there is a project.** `resolve_project_id` refactors off `~/.ai-raccoon/memory.db` onto the project's own `.ai-badger/` directory. `AI_BADGER_PROJECT_ID` explicit-wins stays; nested-`.ai-badger` ambiguity still refuses. L1's leg-scoped-cursor fix rides along (`None` legitimately means "not an ai-badger project" — Hermes fires repo-less). Open design point for the plan: the id itself — minted at scaffold time into `.ai-badger/` (lean; den-refresh backfills) vs derived from path/repo. |
| D3 | L2 — `AI_BADGER_TEST_HOLD` holds indefinitely | **CHANGE — arm-env gate** | Owner asked why the env ships in production at all. Answer: it is consulted (one `if` in `_hold_at`, `badger_store.py:87–114`) because the exactly-once process-race E2E must freeze the *shipped* script; arming is the leak risk. Resolution: consultation stays, **hold honoured only when a second arm env (test preconfiguration) is set** — a stray `HOLD` alone becomes inert. |
| D4 | L4/L5 — pi/Hermes consumed-at-start shapes | **APPROVE + note = defer the spawn** | Owner: "what we want is to consume messages — not just read them." pi start-spawn moves to `before_agent_start` so read and inject coincide; dissolves L5's turn-1 skip. Contract note: pinned scenario "pi session start delivers" needs `.feature` wording amendment. Hermes: same treatment if a seam exists, else documented shape. |
| D5 | L6 — Copilot `sessionEnd` evidence gap | **APPROVE** | Residual-risk line in the 0.156.0 changelog. |
| D6 | L8 — identity asserted, not authenticated | **APPROVE** | Machine-local trust boundary documented in send-message SKILL + changelog. |
| D7 | L9 — Copilot hook rows lack the `-f` guard | **APPROVE** | Copilot `adjust_hooks` emits the `if [ -f … ]` guard, matching Claude's adjuster. |

## Not answered

_(none — every item has a verdict; D2/D3 re-ruled in chat, recorded above)_
