# ADR-0037 — Accept provider/model pins

**Date:** 2026-10-06
**Status:** Accepted
**Amends:** ADR-0027 (pi model pins) and ADR-0031 D2 (planner model routing).

## Context

pi identifies a model as `<provider>/<model>`, splitting at the first slash. The registry
and delegation validator restricted pins to OpenRouter, while scaffold regeneration silently
removed native provider pins. The memory planner uses OpenRouter HTTP directly, so accepting
native pins in the registry also requires refusing them at its transport boundary.

## Decision

Registry ids and pi pins use a shape-only grammar. A provider begins with an ASCII letter or
digit, followed by letters, digits, `.`, `_`, or `-`. Each nonempty model segment begins with
an ASCII letter, digit, `~`, or `@`; later characters also allow `.`, `_`, `:`, `+`, and `-`.
There is at least one model segment after the provider. Nested paths are valid.

Validation consumes the whole string, including its final character. Raw registry and schema
values reject whitespace and control characters. The existing frontmatter reader trims values
before validating them. No provider list, catalog lookup, remapping, or network discovery is
part of admission. Valid pins survive pi regeneration and reach its `--model` argument verbatim.
Defaults and `registryVersion` stay unchanged.

The memory planner requires a resolved `openrouter/` pin with a two-segment `vendor/model`
suffix using ASCII letters, digits, `.`, `_`, and `-`. Other resolved pins return `no-model`
before HTTP. Its environment override retains `vendor/model` with an optional `openrouter/`
prefix. A two-segment native-looking override is indistinguishable from a legacy OpenRouter
API id and remains accepted; nested paths and native punctuation are refused.

## Consequences

Projects can use native providers and local models without losing explicit pins during refresh.
Admission proves syntax only. Provider availability is still pi's responsibility, and provider
policy filtering remains deferred. A native medium registry pin makes the OpenRouter memory
planner fall back to a single search; it does not route that pin to OpenRouter.

The shared conformance fixture checks registry load, emission, schema validation and TypeScript
admission. Scaffold regeneration and planner zero-transport tests cover the boundaries.
