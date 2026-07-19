---
description: 'Plain JavaScript conventions.'
applyTo: '**/*.js,**/*.mjs,**/*.cjs'
---

# JavaScript

- Prefer ES modules (`import`/`export`) over CommonJS in new code unless the runtime/tooling requires otherwise.
- Use `const`/`let`, never `var`. Prefer strict equality (`===`/`!==`).
- Keep async code in `async`/`await` form over raw `.then()` chains for anything beyond a single call.
- If the project has TypeScript available, prefer adding a new module in TypeScript over plain JavaScript; treat plain JS as legacy-compatible, not the default for new code.
- Avoid global mutable state; pass dependencies explicitly.
