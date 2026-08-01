# code-review-checklist extension: ts

## @contract: ts: TypeScript Quality
- [ ] **No `any` types in application code** — zero tolerance
- [ ] **No `as` type assertions except for `JSON.parse` and `event.target.value`**
  — unsafe `as` casts bypass type checking
- [ ] **Route params are type-safe** — use `z.string().parse(param)` or a
  guard clause that returns early. No eslint-disable on route params.
- [ ] **Types are explicitly defined** — every type referenced in an API call
  must have a corresponding interface/type definition (not inline any).
- [ ] **Client types mirror backend record types** — field names, optionality,
  nesting all match. Enum values use the wire format.

## @cross-cutting: ts: Browser Security
> Applies to code that runs in a browser. For a server-side TypeScript project,
> mark the browser-only items N/A rather than skipping the section silently.
- [ ] **No untrusted value reaches a DOM XSS sink** — `innerHTML`/`outerHTML`,
  `insertAdjacentHTML`, `document.write`, `dangerouslySetInnerHTML`, `eval` /
  `new Function`, a string passed to `setTimeout`/`setInterval`, or an event
  handler attribute set from a string. Use `textContent` or the framework's
  escaping path, or sanitize with an audited sanitizer at the insertion point.
- [ ] **A markdown or rich-text renderer with raw HTML enabled has a sanitizer**
  — enabling raw HTML and trusting the source is the same finding as `innerHTML`.
- [ ] **`href`, `src` and programmatic navigation from untrusted data are
  scheme-checked** — `javascript:`, `data:` and `vbscript:` rejected, target
  origin decided explicitly rather than by string concatenation.
- [ ] **`postMessage` validates `event.origin` and passes an explicit
  `targetOrigin`** — never `"*"` for anything but public data, and the received
  payload is untrusted input, not a typed object.
- [ ] **No token in Web Storage** — `localStorage`/`sessionStorage` is readable
  by any injected script. Prefer `HttpOnly` `Secure` `SameSite` cookies, or
  in-memory with a silent-refresh path.
- [ ] **Cookie-authenticated state-changing requests carry CSRF protection** —
  `SameSite` is a mitigation, not the control.
- [ ] **New inline script or style has not quietly forced `unsafe-inline`** — the
  diff adding it is the moment to re-check the CSP; `unsafe-inline` and
  `unsafe-eval` each need a written reason, with nonces or hashes as the target.
- [ ] **A new third-party `<script src>` is self-hosted or carries `integrity`**
  — an unpinned CDN script, tag manager or analytics snippet is a supply-chain
  hole with no owner.
- [ ] **Source maps and dev-only overlays are absent from the production build**
  — they expose code structure and internal URLs.

> Distilled from the frontend references in the OpenAI `security-best-practices`
> skill ([openai/skills](https://github.com/openai/skills), Apache-2.0); rules
> that a reviewer cannot check against a diff were left there deliberately.
