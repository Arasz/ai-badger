# code-review-checklist extension: dotnet

## @pre-takeoff: dotnet: Pre-Takeoff
- [ ] **No `#pragma warning disable` without justification** — every suppression must have a tracked TODO or documented reason

## @architecture: dotnet: DI & Registration
- [ ] **Every injected type is registered in DI** — trace each constructor
  parameter to `AddSingleton`/`AddScoped`/`AddTransient` or `AddOptions<T>()`.
  If a type is injected but not registered, it will crash at runtime.
- [ ] **Options classes use `AddOptions<T>().Bind()`** — verify each
  `IOptions<T>` / `IOptionsSnapshot<T>` has a corresponding registration.
- [ ] **New `HttpClient` registrations use `AddHttpClient<T>()`** — not raw
  `new HttpClient()` in constructors.

## @architecture: dotnet: Domain Model Purity
- [ ] **Domain types live in Domain project** — repository interfaces (`IRepository<T>`)
  reference types that must be in `Domain`, not `Api` or `Infrastructure`.
- [ ] **Repository interfaces in `Domain.<Feature>` namespace** — not in a generic
  `Domain.Persistence` (which holds only infra-agnostic primitives).
- [ ] **Domain types are `sealed record` with `init`-only properties** — immutable,
  behavior methods return new instances.
- [ ] **Guard clauses use `CommunityToolkit.Diagnostics.Guard`** — not hand-rolled
  `x ?? throw` or ad-hoc `if (x == null) throw`.

## @cross-cutting: dotnet: Error Handling
- [ ] **Domain exceptions mapped via `DomainExceptionProblemMapper`** — new
  exception types must have a case in the mapper's switch expression.
- [ ] **`ResourceNotFoundException` messages are informative** — not `"unknown"`
  or empty string. Include entity type and identifier.

## @backend-runtime: dotnet: High-Performance Logging
- [ ] **New log statements use `[LoggerMessage]` source generators** — not
  `logger.LogInformation(...)` directly. Check for a nested static partial
  `Log` class with attributed methods.
- [ ] **`EventId` is assigned and unique** — each `[LoggerMessage]` has an
  explicit `EventId` that doesn't collide with existing ones.

## @post-merge: dotnet: Post-Merge
- [ ] **`dotnet build` clean on main** — zero errors after merge
- [ ] **`dotnet test` all pass** — no regressions from merge conflicts
