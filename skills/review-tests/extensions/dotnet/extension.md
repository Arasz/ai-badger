# review-tests extension: dotnet

## @tooling: dotnet — run it, do not re-derive it

Read `references/stack-dotnet.md` **when** the target's files are C#/xUnit, for the .NET-specific
rule bodies parented off `universal.md`.

- Read the `dotnet-test:test-anti-patterns` skill **when** the `dotnet-test` plugin is installed,
  and run its Step 5 verdict instead of re-deriving one — Pass 8's calibration line is adapted
  from it verbatim.
- Read the `dotnet-test:detect-static-dependencies` skill **when** the plugin is installed and
  Pass 2 needs an untestable-static scan (`DateTime.Now`, `File.*`, `Environment.*`,
  `new Random()`) — run it before hand-grepping the same categories.
- Read the `dotnet-test:crap-score` skill **when** the plugin is installed and a Pass 7 "which
  expensive test is worth its cost" finding needs a complexity-vs-coverage number instead of a
  guess.
- Read the `dotnet-test:test-gap-analysis` skill's step 4b **when** the plugin is installed,
  before labelling anything `unverified (static reasoning)` — it is where that discipline comes
  from, and it may already have run the check you are about to skip.

**Blind spot none of the above patches:** these plugins mutate production expressions, so an
inert-rule or vacuous-gate finding (`references/archetypes.md`, A17/A18) still needs Pass 1's and
Pass 6's manual walk — no installed tool seeds that class of defect.
