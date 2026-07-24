# code-review-checklist extension: ts

## @contract: ts: TypeScript Quality
- [ ] **No `any` types in application code** — zero tolerance
- [ ] **No `as` type assertions except for `JSON.parse` and `event.target.value`**
  — unsafe `as` casts bypass type checking
- [ ] **Route params are type-safe** — use `z.string().parse(param)` or a
  guard clause that returns early. No eslint-disable on route params.
- [ ] **Types are explicitly defined** — every type referenced in an API call
  must have a corresponding interface/type definition (not inline any).
- [ ] **Client types mirror backend record types** — field names, optionality,
  nesting all match. Enum values use the wire format.
