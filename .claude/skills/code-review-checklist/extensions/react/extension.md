# code-review-checklist extension: react

## @architecture: react: Component Patterns
- [ ] **Sections use shared layout wrapper** — with required `title` and
  `description` string props (e.g., `ContentSection`)
- [ ] **Loading states use shared `QueryLoading` component** — not inline
  `<p>Loading...</p>` or local `LoadingState` components
- [ ] **Error states use shared error component** — not inline
  `<div role="alert">` or local `ErrorState` components
- [ ] **Destructive actions use AlertDialog** (Radix/shadcn) — confirm/dismiss
  flows where the action cannot be undone. Non-destructive edits use Dialog.

## @contract: react: Hook & API Patterns
- [ ] **`@tanstack/react-query` for all data fetching** — `useQuery` for
  reads, `useMutation` for writes
- [ ] **Typed API client** — handles base URL, auth, error responses
  (e.g., `apiFetch<T>(path, init)`)
- [ ] **Query keys are `const` tuples** — e.g., `["feature", "status"] as const`
- [ ] **Mutations invalidate related queries** — via
  `queryClient.invalidateQueries()`. Cache invalidation cascades to related entities.
- [ ] **Optimistic updates use `onMutate` -> cache update -> `onError` rollback**
  — not bare `useMutation` without rollback
- [ ] **Error feedback via toast** — user-facing error feedback on every
  mutation failure

## @contract: react: Test Patterns
- [ ] **Tests use shared `renderWithProviders` helper** — not inline wrappers with manual
  `QueryClientProvider` setup
- [ ] **`retry: false` on both queries and mutations** in test QueryClient
  — prevents test flakiness from retry delays
- [ ] **`userEvent.setup()` then `user.click()` / `user.type()`** — not `fireEvent`
- [ ] **`screen.findBy*` for async content, `screen.getBy*` for sync**
- [ ] **MSW handlers follow `set<Scenario>` naming** — scenario names describe
  the state, not the endpoint
- [ ] **Fixtures use builder pattern** — `buildFoo(overrides)` with `Partial<T>`
  for test-specific customization
- [ ] **Fixtures match actual API response shapes** — wrong fixtures = false green tests

## @patterns: react: Pattern Consistency
- [ ] **New code matches existing patterns in the same repo** — compare against
  established conventions in sibling modules
- [ ] **API base URL comes from a shared constant** — not duplicated across
  handler files
- [ ] **Cross-feature duplication extracted to shared hooks** — if two components
  share ~70 lines of identical logic, extract a hook
- [ ] **Bulk operations consider parallelism** — sequential `for...await` is slow
  for 10+ items. Document why sequential or use `Promise.allSettled()`.

## @post-merge: react: Post-Merge
- [ ] **Frontend lint + test all pass** — no regressions from merge conflicts
