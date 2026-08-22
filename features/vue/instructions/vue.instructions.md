---
description: 'Vue 3 component and UI conventions.'
applyTo: '**/*.vue'
---

# Vue

- Use `<script setup lang="ts">` single-file components with the Composition API; type the
  component contract explicitly — `defineProps<{...}>()`, tuple-syntax
  `defineEmits<{ event: [payload: Type] }>()`, and `defineModel<T>()` for two-way bindings —
  rather than runtime declarations.
- Derive state with `computed`; never mirror derivable data into extra `ref`s that must be kept
  in sync by hand. Reach for a `watch`/`watchEffect` only for genuine side effects, and give
  every watcher-created resource (timers, listeners) a cleanup path (`onScopeDispose`,
  `onUnmounted`, or watcher cleanup).
- Remember that the router reuses a component instance when only route params change: watch the
  param (with `{ immediate: true }`) or use route-level props instead of relying on remounts.
- Extract reusable stateful logic into composables (`useX`) that own their lifecycle; share
  cross-cutting services (notifications, dialogs) through `provide`/`inject` with a typed
  `InjectionKey` and a fail-fast injector, not through global singletons.
- Use Pinia setup stores (`defineStore` with a setup function) for shared server state; keep
  reactivity when consuming them via `storeToRefs`. Model remote-read lifecycle as a status
  union (`idle | loading | ready | error`), not a pile of booleans.
- Keep components below the route level presentational — props in, events out; views own async
  orchestration and error-to-user reporting. Access the backend only through the shared API
  client, and treat the server response as the authoritative state after every mutation.
- Preserve accessibility: semantic HTML and real landmarks, strict heading order,
  keyboard-operable custom controls (Enter and Space), associated labels/accessible names on
  every interactive element, `aria-live` for asynchronous feedback, and
  `prefers-reduced-motion` support for transitions.
- Test components behaviorally with @vue/test-utils: interact through the DOM, assert emitted
  events and rendered output, mock only the API-client boundary; stub `Teleport`/`Transition`
  in jsdom (it never fires `transitionend`) and keep real-browser flows in end-to-end tests.
