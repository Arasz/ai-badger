# explanation — understanding-oriented, why it is like this

Background and reasoning, read away from the keyboard. An explanation is allowed to discuss
alternatives that were rejected, history that no longer applies, and trade-offs nobody has to act
on. Filenames are noun phrases or a `why-` (`why-there-is-one-writer.md`).

An explanation that binds a decision is not an explanation — it is an ADR, and it goes in
`../adr/` where it is immutable.

## Files

- [review-flow.md](review-flow.md): how the `review-flow` skill reviews a pull request, with
  diagrams of the coordinator loop, the phase machine, the verdict and publishing.

`../framework-architecture.md` and `../hermes-claude-compatibility.md` are explanation
pages still at the docs root; re-placing them is a job for the `documentation`
gateway's `migrate-documentation` member, with its own PR.
