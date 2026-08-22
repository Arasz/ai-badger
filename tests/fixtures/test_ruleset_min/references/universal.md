# Universal rules (L1)

Two rules — enough to exercise both `flag: auto` and `flag: argued`, `evidence: strong` and
`evidence: weak`, and a `phase: review-only` rule with no design step. Convention matches the
real universal.md: a bold heading, then a fixed bullet block, then one `*meta:*` line.

**`T1-AAA-01` — Assert something that can distinguish right from wrong.**
- *design:* if the only outcome is "nothing threw", you have not written a test yet.
- *review:* four shapes — zero assertions, NotThrow-only, tautological, commented-out.
- *check:* auto — grep for `NotThrow` / `assertDoesNotThrow` as the sole assertion.
- **severity:** blocker · **evidence:** strong · **flag:** auto
- *absorbs:* `U-ASR-01`, `U-ASR-02`
- *cites:* `governance.md`
- *meta:* pass=1 order=1 phase=6

**`T1-AAA-02` — Never assert on wall-clock time.**
- *design:* assert what the time was a proxy for, never the duration itself.
- *review:* every hit is a finding, regardless of test kind.
- *check:* auto — grep for `Stopwatch|Elapsed|performance.now` inside an assertion call.
- **severity:** major · **evidence:** weak · **flag:** argued
- *absorbs:* `U-ISO-01`
- *cites:* invariant `prove-the-check-fails`
- *meta:* pass=2 order=1 phase=review-only
