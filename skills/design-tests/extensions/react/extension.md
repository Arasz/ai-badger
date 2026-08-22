# design-tests extension: react

## @runner: react: bun runner decision rows
- **Harness:** `bun test`, RTL queries (`getByRole`/`getByLabelText`, never `getByTestId` first).
- **Scoped run:** `bun test <path>` — a path that matches zero files exits 0, so Stage 5's pasted
  output must show a non-zero test count.
- **Runner ladder, cheapest first:** bun (pure logic/hooks) → bun + happy-dom (render, no layout —
  `getBoundingClientRect` is all-zero regardless of CSS) → + MSW (`onUnhandledRequest: "error"`,
  never a live `fetch`) → + fake timers (`vi.useFakeTimers()`/equivalent, restored every
  `afterEach`) → Playwright (real browser — layout, focus order, `:focus-visible`, a11y).
- Read `../review-tests/references/stack-ts-react-browser.md` **before** writing the first test
  when the target renders visible layout, keyboard interaction, or touches network state.

## @red-proof: react: red-proof command shape
- `--run` is the same `bun test <path>` string the target card's `runner` line records, scoped to
  the one file — never the whole suite, or the mutated run measures more than the behaviour under
  proof.
- happy-dom has no layout engine: a `red_proof.py` mutation to CSS or geometry will never redden a
  happy-dom test. That is the runner failing to observe the property at all — move the assertion
  to a Playwright test instead of continuing to mutate a runner that cannot see it.
