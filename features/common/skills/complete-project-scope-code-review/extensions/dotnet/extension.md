# complete-project-scope-code-review extension: dotnet

This is a **config-gated extension** of the base skill, not a standalone skill. It binds the base
skill's stack-neutral steps to .NET.

**Activates when:** `.ai-badger/config.json` lists `dotnet` in `stacks`.

## @stack: dotnet: ground truth and lane tooling

**Phase 0 baseline.** Run `commands.build` and `commands.test` from config and record the exact
counts — a .NET suite reports `passed / failed / skipped` and a duration, and all four numbers
matter. **Record the skipped count separately and enumerate what is skipped**: a skip reports as
green, and a suite whose only real-data correlation check is skipped is measuring nothing there.
Note which trait/category filters CI uses and confirm they *partition* the suite — sum the filtered
counts and compare to the total. A test carrying no `Category` trait is invisible to a
`--filter Category=…` run while still counting in the total.

Also capture, once, at the base commit: warning count (`0 warnings` is a fact worth pinning),
project reference graph, and whether the domain project has any package references it should not.

**Lane accelerators.** Where these are installed, a lane gets more done per token:

- A Roslyn-backed navigator (find-references, dependency graph, DI registrations, type hierarchy,
  dead code, public API surface) — the architecture and code-quality lanes should use it before
  grepping.
- `dotnet-claude-kit:code-review` and `:health-check` — single-agent, diff- or project-scoped .NET
  reviews. They are good *lane implementations*; they are not a substitute for this workflow's
  ground-truth, adversarial and join phases.
- `dotnet-test:test-quality-auditor` and the `assertion-quality` / `test-smell-detection` skills —
  the QA lane's starting sweep. Treat their output as `INFERRED` until the lane re-checks the hits
  at `path:line`; a regex over `[Fact]` methods reports false positives (generic
  `Should.Throw<T>()` reads as assertion-free), and a lane that forwards the raw count without
  tracing every hit has filed a number, not a finding.
- MSBuild binlog tooling when the build itself is the suspect.

## @stack: dotnet: traps that produced real join defects

**Default interface members do not participate in derived-class dispatch.** Adding a member to an
interface as a DIM is the standard way to avoid touching every fake — and it is exactly what makes
this trap fire on merge. If `IStore.GetAsync` is a DIM and `FakeStore` implements `IStore`, a
plain (non-`override`) `GetAsync` on a class *derived from* `FakeStore` never participates in
interface dispatch: calls through the interface land on the DIM and silently return the default.
The suite compiles, the fake looks correct, and the test fails with "not found".

Fix: declare the base fake's member `virtual` with a comment naming the trap, and `override` it in
the derived fake. Check for this by grepping merged fakes for members that shadow rather than
override.

**A test fake that ignores its input.** A `FakeEmbedder` returning a fixed vector regardless of
argument makes a pair of tests pass with their inputs swapped. The test asserts arithmetic, not
behaviour. Before trusting any fake-backed gate, swap the inputs between the positive and negative
case and confirm exactly one fails.

**Silent parameter drop in micro-ORM parameter objects.** Dapper (and equivalents) ignore a
property with no matching `@placeholder` in the SQL. A whole feature can ship — with an ADR, a
benchmark and green tests — writing to a column that does not exist in the statement. Add a test
that reflects over every SQL constant and asserts each parameter-object property has a matching
placeholder; break it with a bogus parameter and watch it go red.

**Skips that report as passes.** An integration test that `return;`s when its backend is
unavailable is reported *passed*, not skipped. A broad `catch (Exception)` around the probe makes
"not provisioned" and "broken" indistinguishable. Gate the skip on the missing precondition and
use the framework's skip API.

**Allocation metrics read across `await`.** `GC.GetAllocatedBytesForCurrentThread()` is per-thread;
reading it either side of an `await` measures two different threads and can report a negative
allocation. A benchmark printing an impossible number is telling you its whole method is wrong.

**Nullable-optional injected dependencies.** `ILogger<T>? logger = null` on a DI-registered type
defeats the analyser rather than helping it; it usually appears as a workaround so existing
parameterless test constructions keep compiling. Route the tests through a shared test-data factory
instead. Optional *data* parameters (`string? workspaceId = null` meaning "not supplied") are a
different thing and are fine.

**Migration ladders are append-only.** Never renumber or delete a ladder step, even when the thing
it created is being removed — the step still runs on existing databases. Leave it as a historical
no-op and add a new step.

## @stack: dotnet: the deletion package

Whole-project reviews on .NET codebases routinely find that the highest-leverage change is
deletion. Two rules learned the hard way:

- **Green tests over unreachable code are why it looked maintained.** A subsystem with two
  dedicated test files, no DI registration and no caller is not covered — it is decorated. Delete
  the tests with the code, in the same change.
- **A deletion grep is an acceptance criterion, and it must be widened until it is honest.** One
  session's first grep would have passed with five of the intended deletions still present. Write
  the grep to name every type, interface and registration in the inventory, and run it as the gate.
