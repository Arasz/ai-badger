## @stack-adjustments: dotnet review adjustments

Apply alongside the generic route when the diff touches C#.

- The checklist's dotnet phases are already in the gates you run: they merge into
  `.ai-badger/skills/code-review-checklist/SKILL.md` at scaffold time, so follow them there
  rather than hunting for a separate dotnet doc.
- Read `.ai-badger/skills/review-tests/references/stack-dotnet.md` **when** judging changed
  xUnit/NUnit tests — it carries the .NET-specific rule bodies (async-assertion traps,
  static-dependency and complexity-vs-coverage tooling pointers) the generic passes point at.
- Treat missing nullability annotations on new public API surface, `ConfigureAwait(false)` absent
  in library code, and `CancellationToken` not plumbed end-to-end as layering findings, not nits.
- Run the project's own `dotnet build` and `dotnet test` from config `commands` **before**
  approving Phase 1 — a green Copilot review is not a build.
