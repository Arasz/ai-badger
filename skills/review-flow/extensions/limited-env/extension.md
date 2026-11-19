# review-flow extension: limited-env

With `limited-env`, run the review flow through the CLI only. No hook starts, checks or
records a step. The coordinator runs each verb itself and reads each result.

- **No hooks.** Run `next` after each `submit`, and read `failures` in its output. No hook
  reminds you of a pending lane or a refused submit.
- **No MCP.** Do not confirm an `mcp:` tool. Without `code-review-graph`, find callers and
  impact with `git diff <base>...<head>` and `grep -rn <symbol>`. Grade that evidence
  `INFERRED`. Without a Jira tool, use ACs that the user pasted (`pasted_acs`).
- **No `uv`.** Run the CLI with `python3 <skill dir>/scripts/review_flow_cli.py <verb> --json '{...}'`.
  This works only if `python3 -c "import pydantic"` succeeds with pydantic 2. If pydantic does
  not import, the CLI writes one line to stderr and stops with exit 3. Then tell the human
  which package is missing. Do not install packages without the human's approval.
- **No `gh`.** `tools-probe` reports `gh` as not available. Do not confirm it.
  `context-probe` then reads no PR text, so paste the PR body and the ACs into files.
  Set `base_ref` in the `context` file to the full 40-hex base commit sha (fetch the base
  branch, then run `git rev-parse origin/<base>`). Without `gh`, submit refuses a branch
  name with `base_untrusted`.
  Run `publish` with `{"flow_id": "<id>", "dry_run": true, "offline": true}`. Without `gh`,
  `publish` is always offline: it makes no GitHub call. Give the human
  `round-N.rendered.md` (the inline comments and the summary, as they would be posted) from
  the flow directory, and ask the human to post them. `threads-fetch` also needs `gh`. For round 2,
  ask the human for the replies as a `{"replies": [...]}` file.
  Without `gh`, `publish` returns no publication, so the flow stays at `result` until a
  real publish on a machine with `gh` returns one.

This extension supplies instructions only. It does not enforce agent behavior.
