# Kind rules — widget (L2)

One rule, `parent`-ed to a real L1 id, sharing that parent's `pass:` so it renders inside the
same review-walk step (MoE-2-ruleset.md §5, "Descent points"). No `phase:` — per §6, only L1
rules populate the design walk.

**`T2-WID-01` — Widget rules require a construction-site test.**
- *design:* one test constructs the input the way production does — not by hand.
- *review:* grep production for the widget's construction sites.
- *check:* auto-unless-listed.
- **severity:** blocker · **evidence:** strong · **flag:** argued · **parent:** `T1-AAA-01`
- *absorbs:* `K-WID-01`
- *cites:* `governance.md`
- *meta:* pass=1 order=2
