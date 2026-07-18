---
description: 'React component and UI conventions.'
applyTo: '**/*.tsx,**/*.jsx'
---

# React

- Use function components with hooks; reach for Server Components/Actions when the framework and deployment target support them, rather than defaulting to client components for everything.
- Place `useMemo`/`useCallback`/`React.memo` at boundaries where profiling (or an obvious re-render cost, e.g. a large list) justifies them — not preemptively on every component.
- Use `Suspense` boundaries around async data-fetching components instead of ad hoc loading-flag state where the framework's data layer supports it.
- Preserve accessibility: semantic HTML, keyboard-operable controls, correctly associated labels, and meaningful accessible names on every interactive element.
- Access the backend only through the generated or shared API client; preserve its error-shape and long-running-operation handling rather than reimplementing fetch calls ad hoc.
- Keep authentication and authorization enforced by the backend; the frontend renders based on what the API returns, it doesn't decide access on its own.
- Use React Testing Library for behavior-focused component and flow tests; mock network calls (e.g. MSW) rather than allowing tests to hit a real backend.
