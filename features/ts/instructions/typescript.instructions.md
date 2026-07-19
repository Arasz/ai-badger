---
description: 'TypeScript language conventions.'
applyTo: '**/*.ts,**/*.tsx,tsconfig.json'
---

# TypeScript

- Use strict mode (`strict: true`). Avoid `any`; model API request/response data and error shapes explicitly with types or a schema-derived type.
- Prefer `type`/`interface` definitions that mirror the actual wire contract over loosely-typed `Record<string, unknown>` grab bags.
- Narrow unions with discriminated tags rather than optional-field guessing; let the compiler prove exhaustiveness on `switch` statements over a union.
- Keep runtime validation (e.g. zod, io-ts) at the boundary where external data enters the system, and derive static types from the schema rather than maintaining both by hand.
- Prefer `readonly` and immutable data shapes for anything that crosses a module boundary.
- Run the type checker (`tsc --noEmit` or the project's build) and linter as part of verifying any change.
