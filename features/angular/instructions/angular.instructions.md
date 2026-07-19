---
applyTo: "**/*.ts,**/*.html,**/*.component.*,**/angular.json"
---

# Angular instructions

Aligned with Angular's official AI guidance. Pull the full context when doing substantial work:
- Best practices: https://angular.dev/assets/context/best-practices.md
- LLM context index: https://angular.dev/llms.txt (full: https://angular.dev/assets/context/llms-full.txt)
- Editor rules (Copilot/JetBrains/VS Code): https://angular.dev/assets/context/guidelines.md
- Angular Agent Skills: https://angular.dev/ai/agent-skills

## TypeScript
- Strict type checking; prefer inference when the type is obvious.
- Avoid `any`; use `unknown` when the type is uncertain.

## Components & DI
- Always use **standalone** components. Do NOT set `standalone: true` (it's the default in v20+).
- Keep components small, single-responsibility. Prefer inline templates for small components.
- Use `input()` / `output()` **functions**, not the `@Input()`/`@Output()` decorators.
- Use `inject()` instead of constructor injection.
- Do NOT use `@HostBinding` / `@HostListener`; put host bindings in the `host` object of the decorator.
- Do NOT set `changeDetection: OnPush` explicitly — it's the default in v22+.

## State
- Use **signals** for local/component state and `computed()` for derived state.
- Do NOT use `mutate` on signals — use `set` or `update`. Keep transformations pure.
- Use the `async` pipe for observables. Do not assume globals like `new Date()` are available.

## Templates
- Use native control flow (`@if` / `@for` / `@switch`), not `*ngIf` / `*ngFor` / `*ngSwitch`.
- Do NOT use `ngClass` / `ngStyle`; use `class` / `style` bindings.
- Keep templates simple — no complex logic in the template.

## Forms, services, assets
- Prefer **Signal Forms** (`@angular/forms/signals`) for new forms (stable v22+); otherwise Reactive forms.
- Singleton services: `providedIn: 'root'`. Implement lazy loading for feature routes.
- Use `NgOptimizedImage` for static images (not for inline base64).

## Accessibility (non-negotiable)
- MUST pass all AXE checks and follow WCAG AA minimums: focus management, colour contrast, ARIA.
