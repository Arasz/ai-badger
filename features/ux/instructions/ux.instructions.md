---
description: 'Design conventions for user-facing surfaces.'
applyTo: '**/*.tsx,**/*.jsx,**/*.vue,**/*.svelte,**/*.razor'
---

# User-facing surfaces

- Design the empty, loading, partial and error states next to the success state; each one names what happened and what the user can do next, rather than showing a blank region or a spinner with no end.
- Count the steps a task costs — screens, prompts, confirmations, keystrokes — and remove any step that exists only to suit the implementation.
- Write text in the user's terms, naming the thing and the next action; never let an internal identifier, exception type or status code stand as the whole message.
- Reuse the project's existing components, tokens and patterns instead of adding a one-off, and treat the project's design or brand document as the reference where one exists — not your own taste.
- Make destructive and irreversible actions visibly different from ordinary ones, and prefer an undo over a confirmation dialog wherever the data allows it.
- Never make a failure cost the user their input: preserve what they typed across an error, a retry or a reload.
- When a surface looks wrong, check what feeds it before restyling it — a value that never arrives and a value styled badly look identical from the outside.
