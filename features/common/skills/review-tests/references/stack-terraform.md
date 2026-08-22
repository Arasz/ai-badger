# Stack — Terraform

No researched ruleset yet — see `governance.md` for the bar a rule must clear
before more are added here. Every L1 (`T1-*`) and L2 (`T2-*`) rule already
applies unchanged. One seed below is proven locally; severity is capped at
`minor` for every rule in a stub file regardless of the defect's real cost,
because it has not yet been through the full evidence/parent review a
researched stack file gets.

#### `T3-TF-01` — Add or update a failing `tests/*.tftest.hcl` assertion before changing Terraform behaviour.
- *design/review/check:* already stated in full at `terraform.instructions.md` —
  cited, not restated, per this file's own governance.
- **severity:** minor (see note above on the stub severity cap) · **evidence:** strong
- *parent:* `T1-PRF-01` · *cites:* `terraform.instructions.md`

## How to contribute a rule

Read `governance.md` §9.1 before adding anything: a stack rule needs a `parent:`
L1/L2 id, a real proven failure, and a falsifying `check:`.
