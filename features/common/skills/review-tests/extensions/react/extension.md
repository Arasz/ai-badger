# review-tests extension: react

## @runner: react — what the runner cannot see

Read `references/stack-ts-react-browser.md` **when** the target's files are `.ts`/`.tsx`, for the
React/browser-specific rule bodies.

- A DOM shim with no real layout engine (bun's default `happy-dom` environment) cannot see CSS
  layout, sizing, scroll dimensions, or pseudo-element content — a suite green under it proves a
  structural/class contract, never appearance. Route anything layout- or accessibility-dependent
  to a real browser before trusting a Pass 0 "the runner can observe this" verdict.
- Run the suite once with `bun test --no-isolate` and once with a fixed `--randomize` seed
  **when** Pass 2 needs to probe for shared-module state or ordering dependence — a suite that
  only passes isolated or only in one order still fails Pass 2, even though the default run stayed
  green.
- An unhandled network request during a test is a Pass 0/Pass 1 finding on its own **when** MSW
  (or the project's stub layer) is not configured to error on one — a request that silently passes
  through is exactly the "runner cannot observe the property" failure Pass 0 exists to catch.
