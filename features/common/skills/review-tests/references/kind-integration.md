# kind-integration

Applies when the test drives a real dependency engine — a container, an emulator, a real HTTP
pipeline — at the version production runs. The runner is whatever brings that engine up
(Testcontainers, `WebApplicationFactory`, an Aspire-driven emulator); it can see what a fake
cannot, which is exactly why several of these rules are the kind-specific instance of a `T1-CST-05`
or `T1-ISO-0x` finding rather than new content — follow the `parent:` pointer for the full body.

**`T2-INTG-01` — Integration means the real dependency engine, at the version production runs.**
- *design:* no in-memory provider standing in for the real engine; pin the container tag to production's major version.
- *review:* an in-memory database provider hides real SQL, transactions and constraints — it is not integration, it is a differently-shaped unit test.
- *check:* auto — `UseInMemoryDatabase` or equivalent; container tag vs production version.
- **severity:** blocker · **evidence:** strong · **flag:** auto · **parent:** `T1-CST-05`
- *cites:* MS Learn EF testing-without-the-database.
- *meta:* pass=0 order=1

**`T2-INTG-02` — Schema and migrations are applied by the same mechanism production uses.**
- *design:* run the real migration tool against the test database; never a schema-sync shortcut.
- *review:* a schema built by an ad hoc "create everything" call tests a database that will never exist in production.
- *check:* argued.
- **severity:** major · **evidence:** strong · **flag:** argued · **parent:** `T1-CST-05`
- *cites:* dotnet-claude-kit `testing`.
- *meta:* pass=0 order=1

**`T2-INTG-03` — Assert the thing only the real backend can prove.**
- *design:* name, before writing the test, the defect this level catches that a fake-backed unit test cannot.
- *review:* query text, predicate semantics, partition/tenancy arguments, constraints, rollback, ordering, collation — a test re-asserting what the fake already asserts bought a container for nothing.
- *check:* argued.
- **severity:** major · **evidence:** strong · **flag:** argued · **parent:** `T1-CST-02`
- *cites:* `evidence.md` (test-suite-shape).
- *meta:* pass=7 order=29

**`T2-INTG-04` — Wait on a readiness signal, never on a delay; wait before the first call, not after the first failure.**
- *design:* use the engine's own readiness API (a health check, a notification service) as the sync point.
- *review:* a fixed delay before the first call is the same defect as a sleep mid-test — it just moves.
- *check:* auto-unless-listed.
- **severity:** blocker · **evidence:** strong · **flag:** auto-unless-listed · **parent:** `T1-ISO-02`
- *absorbs:* `N-ASP-01`
- *meta:* pass=2 order=11

**`T2-INTG-05` — Each test or class gets its own namespace inside the shared dependency: its own database, schema, prefix, or container.**
- *design:* never a fixed literal name for a shared resource; derive it from the run/worker id.
- *review:* two runs sharing a namespace turn a clean run into a false failure and a dirty run into a false pass.
- *check:* auto — hardcoded resource names; confirm a cleanup counterpart exists.
- **severity:** blocker · **evidence:** strong · **flag:** auto · **parent:** `T1-ISO-06`
- *cites:* `evidence.md` (one-apphost-at-a-time).
- *meta:* pass=2 order=11

**`T2-INTG-06` — Record what the emulator does not model.**
- *design:* n/a — a documentation rule that ships with the emulator lane, not with any one test.
- *review:* an emulator is a double with a container around it; its divergences (indexing, accounting, consistency, auth, error codes) are exactly where a green emulator test and a red production call diverge.
- *check:* auto-unless-listed — does a current document name the emulator's known gaps?
- **severity:** major · **evidence:** strong · **flag:** auto-unless-listed · **parent:** `T1-CST-04`
- *meta:* pass=0 order=4

**`T2-INTG-07` — The integration lane is excluded from the PR gate only if what it covers is named, and it runs somewhere on a schedule.**
- *design:* wire the lane into a nightly or scheduled run before excluding it from the PR gate; name what it covers in the same change.
- *review:* an excluded lane with no schedule and no coverage statement is a lane nobody is watching.
- *check:* auto-unless-listed.
- **severity:** major · **evidence:** strong · **flag:** auto-unless-listed · **parent:** `T1-CST-03`
- *cites:* `evidence.md` (test-suite-shape).
- *meta:* pass=0 order=3

**`T2-INTG-08` — One shared expensive fixture per class, disposed deterministically; never one container per test method.**
- *design:* stand the container up once per class (`IClassFixture`/equivalent), and tear it down in a lifecycle hook, not a happy-path line.
- *review:* a container per test method is the cost `T1-CST-02` exists to catch; a shared fixture with no deterministic teardown leaks into the next run.
- *check:* argued.
- **severity:** minor · **evidence:** strong · **flag:** argued · **parent:** `T1-ISO-06`
- *cites:* dotnet-claude-kit `testing`.
- *meta:* pass=2 order=11
