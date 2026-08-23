# Archetype table (fixture)

Minimal two-row table matching the real `archetypes.md`'s shape closely enough to exercise F2:
a rule id resolving in column 4, and a non-rule `invariant \`slug\`` token that column 4 also
carries on the real table (A10) and which `[BAD-ARCHETYPE]` must not flag.

| id | Archetype | Layer | Rule demanding the guard | Proof mutation | Runner |
|---|---|---|---|---|---|
| A01 | Sample boundary defect | domain | `T1-AAA-01` | flip a comparison | unit |
| A02 | Sample construction defect | domain | `T2-WID-01`, invariant `prove-the-check-fails` | skip the site | unit |
