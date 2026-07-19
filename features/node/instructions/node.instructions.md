---
description: 'Node.js/Bun runtime and package-management conventions.'
applyTo: '**/package.json,**/bun.lock,**/*.mjs,**/*.cjs'
---

# Node / Bun

- Use whichever package manager the project has already committed a lockfile for (Bun's `bun.lock`, or npm/pnpm/yarn's equivalent); don't introduce a second one or a competing lockfile without an explicit decision to migrate.
- Keep scripts in `package.json` as the single entry point for build/test/lint/run — document any script that needs a non-obvious environment variable or flag.
- Prefer the runtime's native APIs (fetch, test runner, file APIs) over adding a dependency when the native API already covers the need, unless the project has a documented reason to prefer a specific library (e.g. a particular test framework for its assertion/reporting style).
- Never write directly to a shared datastore from a Node process that isn't the designated single writer — call the API layer instead.
- Run the project's `test`, `lint`, and `build` scripts from the directory that owns the `package.json` after changes.
