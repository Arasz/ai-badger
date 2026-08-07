---
name: dotnet-domain-modeling
description: "Use when modeling immutable C#/.NET domain layers: sealed records with required/init props, CommunityToolkit.Diagnostics guards (and when to hand-roll them), state-transition methods, policy objects, extension-point interfaces (DIM), FluentValidation nested validators, ArchUnitNET purity enforcement — with TDD for pure domain layers. Triggers: DDD aggregates/value objects, domain-purity rules, validator design."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [dotnet, csharp, domain-driven-design, records, communitytoolkit, ddd]
    related_skills: [test-driven-development, refactoring-fix, safe-bulk-refactoring, dotnet-mcp-server]
---

# .NET Domain Modeling

Immutable domain models in C# using sealed records, CommunityToolkit.Diagnostics guard clauses, and pure-domain TDD.

## When to Use

- Building DDD aggregates, entities, value objects in C#
- Domain layer must stay pure (no infra, HTTP, persistence, LLM dependencies)
- State machine / lifecycle transitions on domain objects
- Policy objects that evaluate decisions based on aggregate state + confidence thresholds
- Extension-point interfaces (repository, monitor, adapter)

## Immutable Record Pattern

### Structure

```csharp
using CommunityToolkit.Diagnostics;

namespace MyApp.Domain.Feature;

/// <summary>Brief doc comment — state contract, not rationale.</summary>
public sealed record MyAggregate
{
    public required string Id { get; init; }
    public required string UserId { get; init; }  // partition key
    public MyStatus Status { get; init; } = MyStatus.Draft;
    public required DateTimeOffset CreatedAt { get; init; }

    // Immutable transition: guard + return new instance
    public MyAggregate Activate()
    {
        if (Status != MyStatus.Draft)
            ThrowHelper.ThrowInvalidOperationException(
                $"Cannot activate from '{Status}'; only 'Draft' is allowed.");
        return this with { Status = MyStatus.Active };
    }
}
```

### Conventions

| Convention | Example |
|---|---|
| `sealed record` | No inheritance, value semantics, `with` expressions |
| `required` properties | Mandatory fields enforced at compile time |
| Default values on optional | `Status { get; init; } = Status.Draft;` |
| Methods return new instance | `return this with { ... };` — never mutate |
| Guard at entry | `ThrowHelper.Throw*` or `Guard.*` |
| Factory methods | `static MyAggregate Create(...)` for known entry points |
| camelCase JSON | Use `[JsonPropertyName("camelCase")]` if serialized |
| Minimal doc comments | 1–3 lines, state contract not rationale |

## Constructor-Validated Records

When a record must reject invalid input **at construction** (blank ids, out-of-range limits), use an explicit constructor with guards plus get-only auto-properties. Optional params get defaults in the constructor signature; callers use named arguments.

```csharp
public sealed record MemoryWriteRequest
{
    public MemoryWriteRequest(
        string projectId,
        string content,
        string? context = null,
        bool isolated = false,
        string? agentId = null,
        string? workspaceId = null)
    {
        Guard.NotNullOrWhiteSpace(projectId, nameof(projectId));
        Guard.NotNullOrWhiteSpace(content, nameof(content));

        ProjectId = projectId;
        Content = content;
        Context = context;
        Isolated = isolated;
        AgentId = agentId;
        WorkspaceId = workspaceId;
    }

    public string ProjectId { get; }
    public string Content { get; }
    public string? Context { get; }
    public bool Isolated { get; }
    public string? AgentId { get; }
    public string? WorkspaceId { get; }

    // Computed property — no backing field, so record equality ignores it.
    public string ContextName => ContextNaming.WorkspaceContext(WorkspaceId!);
}
```

Why not the alternatives:

| Shape | Problem |
|---|---|
| Positional primary ctor + same-signature chaining ctor (`: this(...)` + validation) | Legal but easy to get wrong (defaults on both ctors, ambiguity risk) |
| `required ... init` properties | Compile-time presence, but cannot run validation logic |
| Hand-rolled `?? throw` / `if (x == null) throw` inline | Repo invariants prefer a guard helper — reads as intent, consistent exception type/message |

Key nuance: **computed (expression-bodied) properties are NOT part of record value equality** — they have no backing field, so the synthesized `Equals`/`GetHashCode` skip them. A derived property (e.g. `Context => ContextNaming.WorkspaceContext(Id)`) can therefore live inside a value-equality record safely. Stored auto-properties ARE compared.

Guard exception types: `ArgumentException` for blank strings, `ArgumentOutOfRangeException` for out-of-range numerics. Tests assert the specific type, not the base.

## CommunityToolkit.Diagnostics Guards

If the repo's clean-layering rule forbids new domain packages (a domain dependency is an ADR-level decision), hand-roll a tiny `internal static` Guard class instead — see `references/pure-domain-project-scaffolding.md` for the shape.

Core facts: `Guard.IsNotNull/IsNotNullOrWhiteSpace/IsGreaterThan/IsLessThanOrEqualTo` and `ThrowHelper.Throw*` work as expected; `Guard.IsEqualTo` has notnull+IEquatable constraints. The three real pitfalls, with code: `references/communitytoolkit-guards-full.md`.

1. **Guards return void** — cannot compose in field initializers (`CS0023`/`CS0029`). Use the throw-helper coalesce (`x ?? ThrowHelper.ThrowArgumentNullException<T>(nameof(x))`) when the guard must run at field-init time.
2. **`??`-coalescing ctor-args test helpers swallow explicit `null!`** — the default substitutes, the guard never fires, the test fails "should throw but did not". Use one full ctor call per guard with the target arg literally `null!` + a `ParamName` assertion.
3. **With `<Nullable>enable</Nullable>` + DI, ctor null-checks are dead code** — delete them; keep guards for real value validation (whitespace/range).

## State Machine Pattern

### Enum States

```csharp
public enum SignalDisposition { Proposed, Applied, Dismissed }
```

### Transition Methods

Each valid transition is a method that:
1. Guards preconditions (current state must be valid source)
2. Returns new instance with target state set
3. Throws `InvalidOperationException` on invalid source state

```csharp
public ChannelSignal Dismiss()
{
    if (Disposition != SignalDisposition.Proposed)
        ThrowHelper.ThrowInvalidOperationException(...);
    return this with { Disposition = SignalDisposition.Dismissed };
}

public ChannelSignal Apply()
{
    if (Disposition != SignalDisposition.Proposed)
        ThrowHelper.ThrowInvalidOperationException(...);
    return this with { Disposition = SignalDisposition.Applied };
}
```

### Exception Pattern

- **Invalid state transition**: `InvalidOperationException` (or custom domain exception)
- **Invalid argument**: `ThrowHelper.ThrowArgumentException` / `Guard.IsNotNull*`
- **Precondition failure**: `ThrowHelper.ThrowInvalidOperationException`

## Policy Object Pattern

When a domain decision depends on multiple inputs (aggregate state, signal classification, confidence threshold) and the logic is too complex for a single transition method, extract it into a **standalone policy class**.

```csharp
public sealed class SignalTransitionPolicy
{
    private readonly ChannelMonitoringOptions _options;

    public SignalTransitionPolicy(ChannelMonitoringOptions options)
    {
        Guard.IsNotNull(options);
        _options = options;
    }

    public SignalTransitionDecision Evaluate(ChannelSignal signal, Application application)
    {
        // Guard inputs, then evaluate decision tree:
        // 1. NoOp guards (no classification, already disposed, aggregate terminal, etc.)
        // 2. Allowed-transition check via ApplicationStateMachine.IsAllowed()
        // 3. "At or past" ordinal check for idempotent detection
        // 4. Confidence gate → Apply vs Propose
        // 5. Terminal target → always Propose
    }
}
```

### Conventions

| Convention | Example |
|---|---|
| Options record for thresholds | `ChannelMonitoringOptions` with `AutoApplyConfidenceThreshold` |
| Decision record as output | `sealed record SignalTransitionDecision` with `Type`, `TargetState`, `Reason` |
| Decision enum | `TransitionDecisionType { Apply, Propose, NoOp }` |
| Reason string includes source identity | `"Auto-applied from signal '{Id}' (source: {Source})."` |
| Class is `sealed class`, not record | Policies have no identity; they're services |

### Testing Policy Objects

For state-machine-dependent policies, see `references/state-machine-policy-testing.md` for:
- Walking a state machine forward in test helpers
- Ordinal "at or past" comparison for idempotent/out-of-order detection
- Decision-category test matrix and note-content verification

## Injectable Components (Project Convention)

In injected-dependency projects: **static classes are reserved for
extensions and constants. Classes with logic must be injectable components with interfaces.**
See `references/injectable-components-pattern.md` for the rule, conversion pattern, and
migration priority.

## Extension-Point Interfaces

Interfaces live in the domain layer; implementations live in infrastructure.

```csharp
namespace MyApp.Domain.Feature;

public interface IChannelMonitor
{
    string ChannelType { get; }
    Task<IReadOnlyList<ChannelSignal>> FetchNewSignalsAsync(
        string userId, string? watermark, CancellationToken ct);
}

public interface IMyRepository
{
    Task<MyAggregate?> GetByIdAsync(string id, string userId, CancellationToken ct);
    Task<IReadOnlyList<MyAggregate>> GetByParentIdAsync(string parentId, string userId, CancellationToken ct);
    Task<MyAggregate> UpsertAsync(MyAggregate entity, CancellationToken ct);
}
```

Conventions:
- `CancellationToken ct` as last parameter
- `string userId` for partition-key scoping
- `IReadOnlyList<T>` for collections (not `IEnumerable<T>` for async)
- Nullable return for single-entity lookups

### Evolving Interfaces with Default Interface Methods (DIM)

When an existing interface needs a new method but all current implementors should keep working unchanged, add the method with a **default implementation**. This avoids a breaking change across all implementations.

**Pattern:** Add `string? TryGetUserId(AuthenticatedPrincipal) => null;` to `IPrincipalAllowlist`. The default returns `null`, meaning "I don't resolve dynamic IDs — fall back to the caller's static config." New implementations (e.g., `CosmosBetaAllowlist`) override it to return a real userId; old implementations (e.g., `SingleUserAllowlist`) inherit the `null` default and continue working.

```csharp
public interface IPrincipalAllowlist
{
    bool IsAllowed(AuthenticatedPrincipal principal);

    // NEW — default null means "caller should use IsAllowed + config-driven userId"
    string? TryGetUserId(AuthenticatedPrincipal principal) => null;
}
```

**Caller pattern (PrincipalResolver):** Try the new method first, fall back to the old contract:

```csharp
var userId = allowlist.TryGetUserId(principal);
if (userId is not null)
    return new PrincipalResolution.Authenticated(userId);

// Fallback: static allowlist path
return allowlist.IsAllowed(principal)
    ? new PrincipalResolution.Authenticated(options.UserId)
    : new PrincipalResolution.Forbidden(...);
```

**When to use:**
- Migrating from a static/single-user implementation to a dynamic/multi-user one
- The new method returns richer data (userId) than the existing bool method
- You want existing tests to pass unchanged (default `null` → falls through to old path)

**Pitfall:** DIM requires C# 8+ (already available in this project). The default implementation is only used when the implementor does NOT override it — if `SingleUserAllowlist` explicitly implements `TryGetUserId`, the default is ignored.

## Domain Purity Enforcement

Use ArchUnitNET (or similar) to enforce no infra dependencies:

```csharp
private const string ForbiddenPattern = @"^(Microsoft\.Azure|Azure\.|Microsoft\.EntityFrameworkCore|System\.Net\.Http)";

[Fact]
public void Domain_types_do_not_depend_on_infra_namespaces()
{
    var rule = Types()
        .That().ResideInAssembly(typeof(DomainAssemblyMarker).Assembly)
        .Should().NotDependOnAny(Types().That().ResideInNamespaceMatching(ForbiddenPattern));
    rule.Check(Architecture);
}
```

## FluentValidation Nested Validators (Project Convention)

When adding FluentValidation validators that nest (child validators, property-level rules, camelCase property paths, constructor guards → boundary validators), follow the full convention in `references/fluentvalidation-nested-validators.md`.

## TDD Workflow for Domain Models

RED → minimal domain types → GREEN → purity re-check, with the stub-first recipe for data-heavy models and the 'explore existing patterns first' step: `references/tdd-workflow-domain-models.md`. Brand-new pure-domain project scaffolding: `references/pure-domain-project-scaffolding.md`.

## Deterministic Classification Pipeline

When a domain feature processes external signals (emails, notifications, etc.) through multiple stages before taking action, use a **pipeline of static utility classes**. Each stage is a pure function — no HTTP, persistence, or LLM dependencies. Stage sequence, per-stage test patterns, and the LLM-fallback classifier: `references/deterministic-classification-pipeline.md`; signal correlation & bootstrap import: `references/signal-correlation-and-bootstrap-import.md`; transport→repository ingestion with cursor durability: `references/ingest-wiring-pattern.md`.

For financial/tax domain modeling (rate tables, rounding, progressive tax), see `references/financial-domain-modeling.md`.

## HTTP Endpoint Testing (Azure Functions)

When writing tests for Azure Functions HTTP-triggered endpoints (non-durable), see `references/http-endpoint-testing-patterns.md` for:
- Test harness setup (FunctionContext, DefaultHttpContext, response body reading)
- camelCase enum serialization pitfall and detection
- userId-scoping test pattern
- In-memory repository with optimistic concurrency
- Middleware testing (AuditMiddleware, PrincipalResolutionMiddleware — GetHttpContext via Items dict)
- Status endpoint testing (DurableTaskClient.GetInstanceAsync mocking)
- PUT round-trip with FluentValidation (save + validate + return)
- Optional body parameters on Azure Functions methods
- Required NuGet packages

## Recommendation Engine Pattern

When a feature produces recommendations from multiple deterministic heuristics (with optional LLM prose framing but never LLM-authored numbers), use the static-heuristic + engine pattern. Heuristics are static methods operating on pre-computed domain results; the engine orchestrates calculator + heuristics, clamps between floor/stretch, and refuses unsupported inputs. Tests assert `Source == Deterministic` to prove no LLM touched the figures. See `references/recommendation-engine-pattern.md` for the full structure, testing strategy, and pitfalls.

```
Inbound message → RelevanceFilter → Correlator → Classifier → Policy → Transition
                   (is it job mail?) (which app?) (what kind?) (should we act?)
```

Full structure, conventions, testing strategy, and pitfalls: `references/recommendation-engine-pattern.md`.

## Infrastructure Adapter Pattern (External Services)

When implementing a new external-service integration (Gmail API, LinkedIn, etc.), follow the full 7-step sequence in `references/infrastructure-adapter-pattern.md`. Covers: transport DTO + interface, Fake transport, TDD cycle, monitor implementation, token refresher with deterministic intervention IDs, high-performance logging, and deduplication.

Key distinction from Cosmos persistence: the transport interface lives in Infrastructure (not Domain), Domain only sees the extension-point interface (`IChannelMonitor`), and the adapter maps external wire types to domain signals.

## Cosmos Persistence (Infrastructure Layer)

When implementing the Cosmos repository for a domain entity, follow the full 9-step sequence in `references/cosmos-persistence-implementation.md`. Covers: contract test suite, InMemory fake, CosmosOptions, Cosmos repository, DI, Terraform container, and the easily-forgotten ProvisionCosmosEmulator update.

Two sub-patterns for specialized cases (documented in the same reference):
- **Encrypted document** — when the entity contains sensitive data (API keys, compensation). Entire document encrypted via `ISecretCipher` before persisting; Cosmos stores a wrapper with `EncryptedSecret`. Test with ephemeral `DataProtectionProvider.Create("scope")`.
- **Optimistic concurrency** — when the contract uses `VersionedDocument<T>` (entity + ETag). Uses CreateItemAsync/ReplaceItemAsync with ETag guards and `ConcurrencyConflictException` on conflicts.
- **Simple config document** — when the entity is a single per-user config (userId = id = partition key). Uses ReadItemAsync + UpsertItemAsync with no concurrency. See `references/cosmos-persistence-implementation.md`.
- **Wildcard-ETag upsert** — when `UpsertAsync(entity, etag)` supports `"*"` for blind upsert and real ETags for conditional replace. Uses UpsertItemAsync with optional `IfMatchEtag`. See `references/cosmos-persistence-implementation.md`.

## High-Performance Logging (Project Convention)

Every Infrastructure class that logs uses the nested `static partial class Log` pattern with `[LoggerMessage]` source generators. This avoids boxing allocations and string interpolation in hot paths.

```csharp
public sealed partial class MyChannelMonitor(...) : IMyMonitor
{
    // ... implementation methods ...

    private static partial class Log
    {
        [LoggerMessage(EventId = 1, Level = LogLevel.Debug,
            Message = "Fetching messages for user {UserId} with watermark {Watermark}")]
        public static partial void FetchingMessages(ILogger logger, string userId, string? watermark);

        [LoggerMessage(EventId = 2, Level = LogLevel.Information,
            Message = "Transport returned {RawCount} messages, {UniqueCount} unique for user {UserId}")]
        public static partial void TransportReturned(ILogger logger, int rawCount, int uniqueCount, string userId);
    }
}
```

**Conventions:**
- Outer class must be `partial` (required by source generator)
- Nested class: `private static partial class Log` — always named `Log`
- Sequential `EventId` starting at 1 within each class
- Never log tokens, message bodies, or PII — log IDs, counts, outcomes only
- `ILogger` passed as first parameter (not captured from outer scope)

## Common File Layout

Domain + Infrastructure + Tests layout, naming, and file-per-type conventions: `references/common-file-layout.md`.

## Intervention Sources

When a domain feature raises interventions on another aggregate:

```csharp
// 1. Define the constant
public static class ApplicationInterventionSource
{
    public const string ChannelMonitoring = "channelMonitoring";
}

// 2. Register in the aggregate's LocalInterventionSources
protected override HashSet<string> LocalInterventionSources { get; } =
    [..existing, ApplicationInterventionSource.ChannelMonitoring];

// 3. Test both raise and clear
[Fact]
public void RequireIntervention_from_channelMonitoring_succeeds() { ... }
[Fact]
public void ClearIntervention_from_channelMonitoring_succeeds() { ... }
```

## Exception → ProblemDetails Wiring

When mapping domain exceptions to RFC 7807 ProblemDetails (problem-type constants, switch-case mapping, WriteProblemAsync), follow the full recipe in `references/exception-problemdetails-wiring.md`.

## Testing: Lifecycle Completeness Matrix

Build a transition matrix — N states × M transition methods, one test per cell, invalid paths asserted to throw: `references/lifecycle-completeness-matrix.md`.

## Gotchas
| Pitfall | Fix |
|---|---|
| `Guard.IsEqualTo` fails with nullable/enum types | Use `if` + `ThrowHelper.ThrowInvalidOperationException` — see `references/communitytoolkit-guard-pitfalls.md` |
| InternalsVisibleTo missing for Domain → Domain.Tests | The Domain project does NOT have `<InternalsVisibleTo>` by default. When implementing `internal` methods (e.g., `ExtractJobId`) that tests need to call, add `<InternalsVisibleTo Include="<Proj>.Domain.Tests"/>` to `src/<Proj>.Domain/<Proj>.Domain.csproj`. Without it, tests get `CS0117: 'Type' does not contain a definition for 'Method'`. |
| Shouldly `ShouldContain` on `string?` properties (CS8604) | When testing nullable string properties like `SkipReason` or `Note` with `.ShouldContain(...)`, the C# analyzer flags CS8604 (possible null reference). Fix: use the null-forgiving operator: `.SkipReason!.ShouldContain(...)`. The test assertion itself IS the null check — if SkipReason were null, the test would fail before Shouldly even runs. |
| Missing `required` on constructor-like properties | Use `required` keyword, not `= null!` |
| `Array.IndexOf` returns -1 for states not on the forward path (Failed, Declined) | Guard negative indices before comparing ordinals — return `false` to mean "not comparable" |
| `Guid.NewGuid()` in Durable Functions orchestrator | Use `context.NewGuid()` — see `references/durable-functions-orchestration-pitfalls.md` |
| Entity/workspace ids via `Guid.NewGuid()` | User preference: use **sortable v7 guids** — `Guid.CreateVersion7()` (net9+) for ids that get listed or ordered. v7 embeds a timestamp, so lists sort deterministically by creation order without a separate CreatedAt sort. `Guid.NewGuid()` (v4) is random — fine for true uniqueness, wrong when ordering matters. Workspace ids, session ids, and any "list by recency" entity are v7 candidates. |
| `ThrowsAsync` on abstract DurableTaskClient methods | NSubstitute can't intercept `.ThrowsAsync()` on `Task<T>` returns from abstract methods. Use `.Returns(Task.FromException<T>(ex))` instead — see `references/durable-functions-testing-patterns.md` |
| C# interpolated string `$"\b"` is backspace, NOT regex word boundary | In C# non-verbatim interpolated strings (`$"..."`), `\b` is the backspace escape character (U+0008), NOT the regex `\b` word boundary. So `$"\b{keyword}\b"` produces a pattern with literal backspace chars that never matches. **Fix:** use `$"\\b{keyword}\\b"` (double backslash) for literal `\b` that the regex engine interprets as word boundary. In raw file bytes: `5c62` = single backslash (broken), `5c5c62` = double backslash (correct). Detection: regex with `\b` compiles and runs but silently matches nothing — no exception, no warning. **Quick diagnostic:** use `xxd` on the `.cs` file to check raw bytes at the `$"\b"` position. This is a DIFFERENT issue from .NET's Unicode word-boundary behavior (which is the next pitfall). |
| .NET `Regex \b` word boundary not matching at string start | In C#, `\\b` in `Regex.Matches(text, @"\\bVP\\b")` (verbatim string) correctly produces the regex `\b`, but .NET's word-boundary rules use Unicode categories that differ from PCRE. `\bVP\b` may not match "VP" at string boundaries in .NET when Python/JS match on the same input. **Fix:** replace `\\b` with `string.Contains(word, OrdinalIgnoreCase)` + manual word-boundary check, or use `string.IndexOf` for position extraction. Don't spend multiple iterations tweaking regex patterns — switch to string methods after the first `\\b` miss. |
| Shouldly `ShouldContain(predicate)` shows no detail on failure | When `collection.ShouldContain(x => x.Prop.Contains("X"))` fails, Shouldly reports the predicate but not the actual values in the collection. **Fix:** add a temporary `Assert.Fail` that dumps all actual values: `Assert.Fail($"Actual: {string.Join("; ", items.Select(i => i.Prop))}")`. Remove after fixing. This one-line diagnostic saves multiple blind fix cycles. |
| Injecting `ILlmCostTracker` into LLM-calling classes | Cost tracking is handled by the infrastructure-layer `ILlmCostTracker` decorator that wraps `ILlmClient`. Classifiers and orchestrators do NOT need to inject `ILlmCostTracker` — they just use the correct `StepType` string so the decorator can tag the ledger record. Only inject `ILlmBudgetGuard` for pre-call budget checks. |

For project-specific worked cases (job-search domain, Azure Functions, worktree discipline, locale-sensitive tests), see `references/project-gotchas.md`.

## Durable Functions Orchestrations

When building Azure Durable Functions orchestrations (activities, orchestrators, concurrency gates), see `references/durable-functions-orchestration-pitfalls.md` for:
- Non-deterministic API pitfalls (`Guid.NewGuid()`, `DateTime.UtcNow`)
- Missing usings for workflow types (`LlmStepRetry`, `InterventionCause`)
- `JsonNode.Deserialize` requiring `System.Text.Json` namespace
- Step lifecycle pattern (`ExecuteStepAsync` → park/resolve/skip)
- Conflict retry pattern (`SaveWithConflictRetryAsync`)
- Concurrency gate setup for new pipeline types
- TOCTOU fix: schedule-then-verify pattern (`ScheduleWithConcurrencyGuardAsync`)
- Conflict-aware step merging: re-run mutation against reloaded document

### Testing Durable Functions Pipelines

When writing tests for orchestrations, generators, HTTP-triggered functions, and exception mapping, see `references/durable-functions-testing-patterns.md` for:
- FakeLlmClient/FakeLlmClientFactory setup for generator tests
- Orchestration test patterns (SetupLoad/SetupSave stubs, scenario matrix)
- HTTP function test patterns (FunctionContext/DurableTaskClient substitution)
- Exception mapping test patterns (DomainExceptionProblemMapper verification)
- NSubstitute + DurableTaskClient pitfalls (`ThrowsAsync` vs `Task.FromException`, `TaskName` matchers, nullable params, expression tree null-propagation)
- C# 14 `extension` member syntax in tests
- Required usings for DurableTask test doubles

### Two-Phase Orchestration (Dry-Run + Apply)

When an operation needs user review before committing writes, use two separate orchestrations with separate instance IDs. See `references/durable-functions-orchestration-pitfalls.md` → "Two-Phase Orchestration Pattern" for the full architecture, instance ID discipline, precondition checks, and partial failure handling.
