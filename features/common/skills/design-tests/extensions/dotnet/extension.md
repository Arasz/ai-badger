# design-tests extension: dotnet

## @runner: dotnet: xUnit v3 runner
- **Harness:** xUnit v3 (`Xunit.v3`), assertions via **Shouldly**.
- **Scoped run:** `dotnet test --filter "FullyQualifiedName~<Type>"` — this resolves to zero tests
  and still exits 0, so Stage 5's pasted output must show a non-zero test count, not just exit 0.
- **Clock seam:** inject `TimeProvider`; tests substitute
  `Microsoft.Extensions.Time.Testing.FakeTimeProvider` — never `DateTime.Now`/`UtcNow` inside the
  unit under test.
- **The three-rung ladder**, cheapest first: pure unit (no host) → `WebApplicationFactory<T>`
  (in-process HTTP, real routing/DI) → Testcontainers (a real emulator, `[Trait("RequiresInfra",
  "true")]`-tagged). Push up a rung only when the cheaper one cannot observe the behaviour.
- Read `../review-tests/references/stack-dotnet.md` **before** writing the first test when the
  target touches Cosmos, HTTP, hosted services, or culture-sensitive parsing.

## @red-proof: dotnet: red-proof command shape
- `--run` is the same `dotnet test --filter "FullyQualifiedName~<Type>.<Method>"` string the
  target card's `runner` line records — scope it to the one test, never the assembly, or the
  mutated run measures more than the behaviour under proof.
- A `FakeTimeProvider`-seamed test never blocks on real time; if `red_proof.py`'s mutated run
  hangs or times out, the seam is missing — that is a finding about the test, not the tool.
