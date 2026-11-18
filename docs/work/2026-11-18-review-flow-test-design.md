# Review flow: test design

Test list for task `aib-code-review-coordinator-flow-model`, written before any production code (method: `design-tests`). Each row maps one acceptance criterion to a test, the defect it catches and the concrete mutation that must turn it red. Rows are mutation targets for `review-tests` after implementation.

## Fixture strategy

- Fake `gh` runner: a callable injected into the publisher records every call (method, endpoint, body) and replays canned paged responses. No network, no real `gh`.
- Tmp git repo for base-ref tests: `tmp_path` repo with a base commit and a head commit that edits `.ai-badger/review/rules.json`; rules load with `git show <base>:path`.
- Fixed `now`: every renderer, machine and store call takes `now` as a parameter; tests pass one constant timestamp so goldens are byte-stable.
- Store tests open a tmp `tracking.db`; the CLI tests run the PEP 723 script as a subprocess with `HOME` redirected.
- Fixture parameters are non-degenerate: more than one round, more than one lane, more than one page, a rule cap above zero.

## Test list

| step/ac | test | failure mode | mutation |
| --- | --- | --- | --- |
| skeleton/ac1 | tests/test_expected_skill_names.py::test_expected_skill_names | New skill present on disk but missing from the pinned catalog list, or the count pin goes stale | Delete `review-flow` directory contents so the skill name vanishes, or add it to the derived list only on one side |
| skeleton/ac1 | tests/test_review_flow_skill_doc.py::test_skill_is_in_plugin_and_index | Skill ships in the catalog but not in the plugin copy or `index_build --check` output | Skip the plugin sync for `review-flow`; `index_build.py --check` must exit non-zero |
| store-table/ac1 | tests/test_badger_store_review_flows.py::test_table_created_on_open_of_existing_v3_db | Table only created for new DBs, so an existing v3 DB has no `review_flows` | Move the `CREATE TABLE IF NOT EXISTS review_flows` out of `_DDL` into a fresh-DB-only branch |
| store-table/ac1 | tests/test_badger_store_review_flows.py::test_older_store_copy_opens_db_with_table | A vendored older store copy crashes on the extra table | Make the older copy assert on unknown tables, or add a column the old copy cannot read |
| store-table/ac1 | tests/test_badger_store_review_flows.py::test_cas_conflict_raises | Two writers with the same revision both succeed (lost update) | Drop the `WHERE revision = ?` clause in the update |
| store-table/ac1 | tests/test_badger_store_review_flows.py::test_schema_version_stays_3 | Table addition bumps `SCHEMA_VERSION`, forcing a migration | Set `SCHEMA_VERSION = 4` |
| render/ac1 | tests/test_review_render.py::test_inline_comment_matches_golden | Output layout drifts from the agreed comment format | Swap the order of the severity label and the title in the inline template |
| render/ac1 | tests/test_review_render.py::test_summary_matches_golden | Summary table or marker line changes silently | Change the summary marker text by one character |
| render/ac1 | tests/test_review_render.py::test_golden_depends_on_fixed_now_only | Renderer reads the wall clock, so goldens flake | Replace the injected `now` with `datetime.now()` |
| render/ac2 | tests/test_review_render.py::test_human_part_over_four_lines_raises_render_refused | A long human part is accepted or cut | Raise the limit from 4 to 5 lines |
| render/ac2 | tests/test_review_render.py::test_exactly_four_lines_renders_untruncated | Off-by-one refuses a legal part, or a truncation path appears | Change the check from `> 4` to `>= 4` |
| render/ac2 | tests/test_review_render.py::test_no_truncation_path_in_source | A helper such as `[:4]` or an ellipsis join is added later | Add `lines[:4]` fallback in the renderer instead of raising |
| render/ac3 | tests/test_review_render.py::test_hostile_text_cannot_escape_blocks | Text with `-->`, `<!--`, `</details>` or a backtick fence closes the data block and injects instructions | Remove the escaping of `-->` in the title |
| render/ac3 | tests/test_review_render.py::test_fence_longer_than_longest_run | Fixed three-backtick fence is closed by a three-backtick body | Hard-code the fence to three backticks |
| render/ac3 | tests/test_review_render.py::test_combined_hostile_tokens_parse_clean | Each token is escaped alone but a mix breaks out (property intersection) | Escape only the first token found per field |
| render/ac4 | tests/test_review_render.py::test_guard_sentence_is_first_in_agent_block | Guard sentence placed after the payload, losing its effect | Move the guard line to the end of the block |
| render/ac4 | tests/test_review_render.py::test_dropped_findings_not_rendered_inline | Dropped findings leak into the PR as comments | Iterate over all findings instead of kept findings |
| render/ac4 | tests/test_review_render.py::test_defensive_badge_rendered | DEFENSIVE downgrade shows no badge, so readers cannot tell | Remove the badge branch for `DEFENSIVE` |
| diff-anchor/ac1 | tests/test_review_diff.py::test_right_side_line_for_added_and_context | Added or context line maps to the wrong RIGHT line after an earlier hunk | Use the old-side counter for context lines |
| diff-anchor/ac1 | tests/test_review_diff.py::test_renamed_file_maps_to_new_path | Rename keeps the old path so the comment 422s | Read the `---` path instead of `+++` |
| diff-anchor/ac1 | tests/test_review_diff.py::test_deleted_and_binary_have_no_right_side | Deleted or binary file gets an anchor GitHub rejects | Return line 1 for binary files |
| diff-anchor/ac1 | tests/test_review_diff.py::test_line_outside_every_hunk_is_out_of_diff | Line between hunks anchored inline instead of folded into the summary | Treat the gap between hunks as in-range |
| diff-anchor/ac2 | tests/test_review_diff.py::test_lint_line_maps_to_path_line | Lint output is not parsed into `path:line` | Change the regex so the line group is optional |
| diff-anchor/ac2 | tests/test_review_diff.py::test_lint_windows_path_with_drive_colon | `C:\src\a.py:12` splits at the drive colon | Split on the first colon |
| diff-anchor/ac2 | tests/test_review_diff.py::test_path_line_inside_message_text_not_misparsed | A message such as `see b.py:99` overrides the real location | Use a non-anchored search and take the last match |
| flow-model/ac1 | tests/test_review_flow_model.py::test_unknown_field_refused | A typo field silently ignored (no `extra=forbid`) | Remove `extra="forbid"` from the model config |
| flow-model/ac1 | tests/test_review_flow_model.py::test_unknown_label_refused | An unmapped severity label passes through | Fall back to `minor` for unknown labels |
| flow-model/ac1 | tests/test_review_flow_model.py::test_every_label_of_five_vocabularies_maps | One of the five existing vocabularies loses a mapping | Delete one entry from the mapping table |
| flow-model/ac2 | tests/test_review_flow_model.py::test_invalid_drop_without_basis | Finding dropped with no recorded reason | Make `basis` optional for `drop` |
| flow-model/ac2 | tests/test_review_flow_model.py::test_invalid_downgrade_without_basis | Downgrade with no reason | Remove the basis check on `downgrade` |
| flow-model/ac2 | tests/test_review_flow_model.py::test_invalid_keep_without_severity | Kept finding has no severity | Default severity to `minor` on keep |
| flow-model/ac2 | tests/test_review_flow_model.py::test_invalid_unreachable_without_defensive | `unreachable_in_production` drops the DEFENSIVE marker | Skip the DEFENSIVE requirement |
| flow-model/ac2 | tests/test_review_flow_model.py::test_invalid_published_round_without_publication | A published round with no Publication record | Drop the cross-field validator |
| flow-model/ac2 | tests/test_review_flow_model.py::test_invalid_active_rule_without_activated_by | Active rule with no activation proof | Make `activated_by` optional |
| flow-model/ac2 | tests/test_review_flow_model.py::test_invalid_threads_activation_one_distinct_author | Two threads by one author count as independent | Count thread ids instead of distinct authors |
| flow-model/ac2 | tests/test_review_flow_model.py::test_invalid_worker_supplied_wrong_fingerprint | Worker picks its own fingerprint and defeats dedup | Accept the worker value instead of recomputing |
| flow-model/ac3 | tests/test_review_flow_model.py::test_schemas_generated_and_registered | New schema file exists but is not registered | Remove the registry entry |
| flow-model/ac3 | tests/test_schema_references.py::test_checked_in_schemas_match_generator | Hand-edited schema drifts from the model | Edit one byte of a checked-in schema; the `--check` run must exit non-zero |
| rules-store/ac1 | tests/test_review_rules.py::test_proposed_rule_absent_from_lane_rules | Unconfirmed rule steers lanes | Include `proposed` in the lane filter |
| rules-store/ac1 | tests/test_review_rules.py::test_active_via_maintainer_confirm | Confirm path does not activate | Skip the status change on confirm |
| rules-store/ac1 | tests/test_review_rules.py::test_active_via_script_verified_citation | Citation path does not activate | Return `proposed` after a verified citation |
| rules-store/ac1 | tests/test_review_rules.py::test_active_via_two_independent_threads | Two-thread path does not activate | Require three threads |
| rules-store/ac1 | tests/test_review_rules.py::test_same_author_two_threads_not_independent | One author in two threads activates a rule | Count threads, not distinct authors |
| rules-store/ac2 | tests/test_review_rules.py::test_non_collaborator_reply_never_proposes | A drive-by reply teaches the flow | Drop the author-association check |
| rules-store/ac2 | tests/test_review_rules.py::test_refuse_citation_outside_repo | Citation path escapes the repo (`../`) | Skip path containment |
| rules-store/ac2 | tests/test_review_rules.py::test_refuse_citation_wrong_quote | Quote not in the cited file still verifies | Compare only the line number |
| rules-store/ac2 | tests/test_review_rules.py::test_conflicting_rules_excluded | Two contradicting rules both reach lanes | Skip conflict detection |
| rules-store/ac2 | tests/test_review_rules.py::test_invalid_rules_json_raises_rules_file_invalid | Broken file ignored, flow runs with no rules | Catch the validation error and return an empty set |
| rules-store/ac3 | tests/test_review_rules.py::test_base_ref_rules_win_over_head_edit | A PR that edits `rules.json` rewrites its own review rules (tmp git repo, head commit edits the file) | Read the working-tree file instead of `git show <base>:` |
| rules-store/ac3 | tests/test_review_rules.py::test_cap_31_active_returns_30_and_dropped_1 | No cap, or cap loses the dropped count | Change the cap to 31 or return no `dropped` |
| flow-machine/ac1 | tests/test_review_flow_ops.py::test_every_undeclared_transition_refused | A skipped phase is accepted | Add one extra edge to the transition table |
| flow-machine/ac1 | tests/test_review_flow_ops.py::test_history_records_trigger_and_round | History loses what caused a move | Omit `trigger` from the history entry |
| flow-machine/ac1 | tests/test_review_flow_ops.py::test_refusal_leaves_state_and_revision_unchanged | Refused move still bumps revision (secondary observable) | Increment revision before validating |
| flow-machine/ac2 | tests/test_review_flow_ops.py::test_fingerprint_stable_under_line_shift_and_reword | Same finding re-raised each round after a rebase | Include line number in the hash |
| flow-machine/ac2 | tests/test_review_flow_ops.py::test_fingerprint_changes_with_kind_path_symbol | Distinct findings collapse into one | Drop `symbol` from the hash input |
| flow-machine/ac3 | tests/test_review_flow_scope.py::test_nullable_fact_suppresses_null_deref_in_scope | Known-nullable fact fails to suppress | Ignore facts when scope matches |
| flow-machine/ac3 | tests/test_review_flow_scope.py::test_nullable_fact_keeps_null_deref_outside_scope | Fact leaks to files outside its scope | Match scope by prefix-free substring |
| flow-machine/ac3 | tests/test_review_flow_scope.py::test_config_reload_fact_downgrades_to_nit_defensive | Reload fact drops instead of downgrading | Return `drop` for the reload case |
| flow-machine/ac3 | tests/test_review_flow_scope.py::test_inferred_fact_or_proposed_rule_does_not_drop | Unproven basis removes a real finding | Accept `INFERRED` grade as a drop basis |
| flow-machine/ac3 | tests/test_review_flow_scope.py::test_dropped_findings_stay_in_model | Dropped finding deleted, audit trail lost | Remove the finding from the list on drop |
| flow-machine/ac4 | tests/test_review_flow_ops.py::test_verdict_table_pinned | Verdict wording or mapping shifts | Swap two rows of the verdict table |
| flow-machine/ac4 | tests/test_review_flow_ops.py::test_failed_lane_never_safe_to_merge | A crashed lane yields a green verdict | Treat a failed lane as zero findings |
| publish-github/ac1 | tests/test_review_publish.py::test_first_run_one_review_post_one_summary_post | Wrong call count on the first run | Post one review per finding |
| publish-github/ac1 | tests/test_review_publish.py::test_identical_rerun_zero_writes | Re-run duplicates comments | Skip the body-equality check |
| publish-github/ac1 | tests/test_review_publish.py::test_changed_body_patches | Changed body POSTs a duplicate | Use POST instead of PATCH for the update |
| publish-github/ac1 | tests/test_review_publish.py::test_event_always_comment | Review posted as APPROVE or REQUEST_CHANGES | Map a `blocker` to `REQUEST_CHANGES` |
| publish-github/ac2 | tests/test_review_publish.py::test_spoofed_marker_from_foreign_author_ignored | Foreign comment carrying our marker hijacks the update | Match the marker without the author check |
| publish-github/ac2 | tests/test_review_publish.py::test_marker_on_page_two_found_no_duplicate_post | Pagination stops at page 1 and re-posts | Fetch only the first page |
| publish-github/ac2 | tests/test_review_publish.py::test_deleted_marker_reposted | Deleted summary never returns | Treat a missing marker as success |
| publish-github/ac3 | tests/test_review_publish.py::test_unchanged_anchored_lines_not_resolved | Resolve call fires on threads still valid | Resolve every thread each run |
| publish-github/ac3 | tests/test_review_publish.py::test_refuse_when_head_moved | Posting against a stale head | Skip the head SHA comparison |
| publish-github/ac3 | tests/test_review_publish.py::test_refuse_on_remote_mismatch | Publishing to the wrong repo | Skip the remote check |
| publish-github/ac3 | tests/test_review_publish.py::test_403_exits_2_with_no_write | Permission failure retried or half-written | Map 403 to exit 1 and continue |
| publish-github/ac3 | tests/test_review_publish.py::test_partial_failure_resumes_without_duplicates | Second run after a failed POST duplicates the first comments | Do not record the progress after each write |
| publish-github/ac3 | tests/test_review_publish.py::test_dry_run_writes_nothing | `--dry-run` still calls `gh` for writes | Skip the dry-run branch |
| cli/ac1 | tests/test_review_flow_cli.py::test_each_verb_payload_validates_against_schema | Verb output drifts from its schema | Rename one output key |
| cli/ac1 | tests/test_review_flow_cli.py::test_identical_submit_replay_returns_changed_false | Replay re-applies and bumps revision | Always set `changed: true` |
| cli/ac1 | tests/test_review_flow_cli.py::test_wrong_phase_submit_refused_with_machine_code | Wrong-phase submit accepted or opaque error | Skip the phase check in `submit` |
| cli/ac2 | tests/test_review_flow_cli.py::test_malformed_json_twice_refused_state_unchanged | Garbage worker output corrupts state (run twice, exit 1 each, revision equal) | Write state before parsing |
| cli/ac2 | tests/test_review_flow_cli.py::test_malformed_schema_invalid_json_twice_recorded_in_history | Failures not recorded, so the coordinator loops blind | Skip the history append on refusal |
| cli/ac3 | tests/test_review_flow_cli.py::test_brief_all_seven_kinds_carry_rules_facts_dropped | A brief kind lacks scoped rules, facts or the dropped count | Remove `dropped` from one kind |
| cli/ac3 | tests/test_review_flow_cli.py::test_brief_injected_text_stays_in_data_block_and_capped | PR text becomes instructions, or one huge field floods the brief | Remove the length cap, or emit text outside the data block |
| cli/ac4 | tests/test_review_flow_cli.py::test_context_probe_ac_source_tool_pasted_absent | Wrong AC source chosen, or Jira invented | Return `tool` when no Tools entry exists |
| cli/ac5 | tests/test_review_flow_launch.py::test_pydantic_hidden_exits_3_with_one_stderr_line | Missing pydantic gives a traceback | Remove the import guard |
| skill-doc/ac1 | tests/test_skills_lint.py::test_review_flow_passes_lint | Skill doc violates the catalog lint | Add a bad frontmatter key |
| skill-doc/ac1 | tests/test_review_flow_skill_doc.py::test_verbs_in_doc_equal_verbs_in_cli | Doc names a verb the CLI lacks, or the reverse | Rename one CLI verb |
| skill-doc/ac1 | tests/test_review_flow_skill_doc.py::test_every_brief_names_persona_and_schema | A brief without an owner or output schema | Delete the persona line from one brief |
| catalog-wiring/ac1 | tests/test_code_review_router_skill.py::test_router_routes_to_review_flow | Router never reaches the new skill | Remove the route row |
| catalog-wiring/ac1 | tests/test_sync_plugin_skills.py::test_plugin_copy_in_sync | Plugin copy stale | Edit the catalog skill without a sync |
| e2e/ac1 | tests/test_review_flow_e2e.py::test_two_round_flow_full_assertions | Real phase chain breaks across rounds (fake `gh`, tmp repo, fixed `now`) | Skip `reply_analysis` on round 2 |
| e2e/ac1 | tests/test_review_flow_e2e.py::test_fixture_shape | Fixture drifts from the model so the e2e passes vacuously | Remove a required field from the fixture |
| e2e/ac2 | tests/test_review_flow_e2e.py::test_guard_disabled_cases_fail_for_every_guard | A guard in `GUARDS` has no case that notices its removal | Add a new guard to `GUARDS` with no case; the derived loop must go red |
