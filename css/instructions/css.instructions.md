---
description: 'CSS styling conventions.'
applyTo: '**/*.css,**/*.scss,**/*.module.css'
---

# CSS

- Prefer component-scoped styles (CSS modules, a scoped stylesheet, or the framework's styling convention) over global selectors that can leak across components.
- Use logical/relative units (`rem`, `%`, `fr`) over hardcoded pixel values for anything that should scale with user font-size preferences or viewport.
- Design mobile-first: base styles for the smallest viewport, `min-width` media queries to layer on larger-screen layout.
- Respect `prefers-color-scheme` and `prefers-reduced-motion` where the project supports theming or animation.
- Keep specificity flat — avoid deep selector chains and `!important`; prefer a more specific class over an escalating specificity war.
