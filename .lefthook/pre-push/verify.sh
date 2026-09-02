#!/usr/bin/env bash
# ai-badger local quality gate. One subcommand per lane; `pre-push` selects lanes from
# the changed paths, `all` runs every lane, `doctor` checks the environment and hooks.
# Contract: exit 0 = pass, 124 = the whole-gate deadline killed the lane in flight, any other
# non-zero = a lane failed. Nothing outside those three means anything.
# Targets bash 3.2 (macOS system bash): no associative arrays, no ${var,,}.
set -uo pipefail

_self_abs="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
cd "$(git rev-parse --show-toplevel)" || exit 1
readonly SELF="${_self_abs#"$PWD"/}"

# git exports these to a hook and they point a child's git at THIS repo, so a test building a
# throwaway repo would write to the real one. Dropped after the cd, so a lane sees the same
# environment it would see when run by hand.
# The first nine mirror badger_lib.GIT_LOCATION_ENV, which git_env() strips on the Python side;
# test_the_hook_unsets_every_variable_badger_lib_calls_a_location_variable keeps them in step.
# The last five pin git's behaviour rather than its location, so they are this list's own.
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_PREFIX GIT_NAMESPACE GIT_CEILING_DIRECTORIES \
      GIT_QUARANTINE_PATH GIT_REFLOG_ACTION GIT_AUTHOR_DATE GIT_COMMITTER_DATE GIT_EDITOR

# Keyed by checkout: the pytest lane runs this script in a throwaway repo, and a shared path
# would let that nested run overwrite the log the failure block just cited.
_log_key="$(printf '%s' "$PWD" | cksum | cut -d' ' -f1)"
readonly LOG_DIR="${VERIFY_LOG_DIR:-${TMPDIR:-/tmp}/ai-badger-verify/$_log_key}"
readonly BASE_REF="${VERIFY_BASE:-origin/main}"
# Redirectable for the same reason as LOG_DIR: the pytest lane runs this script, and an
# unredirectable summary collects rows for pushes that never happened.
readonly LOG_SUMMARY="${VERIFY_LOG_SUMMARY:-logs/lefthook.log}"

# One number bounds the whole push. Fifteen per-lane thresholds would be a hand-maintained list
# nothing ever compares against reality, which is the failure the derive-or-delete invariant
# names.
#
# 1200s from the 225 pre-push rows in logs/lefthook.log (measured 2026-08-15): median 85s,
# p90 267s, p95 388s, p99 563s, max 841s. Zero of the 225 exceed 1200s, so this kills nothing
# that has ever legitimately run, while still ending the 2026-08-15 hang — noticed at ~1500s and
# never going to finish — 5 minutes sooner than the operator did. Those rows only exist for runs
# that FINISHED, which is the bias this whole change exists to fix, so the true tail is longer
# than the one measured and the headroom is deliberate.
#
# It is a floor, not a ceiling: what already SIGKILLs this hook on wall clock could not be
# established (no lefthook job timeout, no BASH_*_TIMEOUT_MS, ulimit -t unlimited, TMOUT unset,
# no launchd job), so a kill from outside can still land first and leave no row.
readonly DEADLINE="${VERIFY_DEADLINE:-1200}"

# GNU timeout's convention, reserved for a deadline kill so it can never be confused with a lane
# that exited 143 on its own. Non-zero, so lefthook still refuses the push.
readonly EXIT_TIMEOUT=124

# What the watchdog and the signal trap need to name the run they are ending. run_lanes owns
# RUN_LANES and RUN_START; main sets HOOK before calling it.
HOOK="lane"
RUN_LANES=""
RUN_START=$(date +%s)

# Every lane. `all` runs these, `verify.sh <lane>` dispatches them, and the `gates` job in
# .github/workflows/pylint.yml reads this line to build the list it walks — so a lane missing
# here runs nowhere.
readonly LANES="version-sync index plugin-skills deps docs release paths workflows validate scaffold journey tdd js pi-ts pylint pytest"

# `$1` minus every lane named in `$2`, order preserved.
_without_lanes() {
    local lane dropped keep=""
    for lane in $1; do
        for dropped in $2; do
            [ "$lane" = "$dropped" ] && lane=""
        done
        [ -n "$lane" ] && keep="$keep $lane"
    done
    printf '%s' "${keep# }"
}

# Lanes CI owns, so a push does not — the same three the `gates` job in pylint.yml skips
# because each has a job of its own. pylint.yml runs `verify.sh pytest` and `verify.sh pylint`,
# consumer-journey.yml runs gates/consumer_journey.py; all three are `on: [push]` with no branch
# filter, on the 3.10 this project floors at rather than whatever the developer happens to have.
# A local pass proves less than the CI run it duplicates, and costs the push the most time.
readonly CI_ONLY_LANES="pylint pytest journey"

# What a push runs: derived, so a lane added to $LANES joins it without a second edit.
readonly LOCAL_LANES="$(_without_lanes "$LANES" "$CI_ONLY_LANES")"

# --------------------------------------------------------------------------- python

# Resolve the interpreter that owns this repo's dev dependencies. A linked worktree has no
# .venv of its own, so the main checkout (parent of the common git dir) is the fallback.
_resolve_python() {
    if [ -n "${AIB_PYTHON:-}" ]; then
        printf '%s\n' "$AIB_PYTHON"
        return 0
    fi
    if [ -x "$PWD/.venv/bin/python3" ]; then
        printf '%s\n' "$PWD/.venv/bin/python3"
        return 0
    fi
    local common main_checkout
    common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
    if [ -n "$common" ]; then
        main_checkout="$(dirname "$common")"
        if [ -x "$main_checkout/.venv/bin/python3" ]; then
            printf '%s\n' "$main_checkout/.venv/bin/python3"
            return 0
        fi
    fi
    command -v python3 2>/dev/null
}

PY="$(_resolve_python)"

# --------------------------------------------------------------------------- skipping

# True when VERIFY_SKIP names this lane. Comma- or space-separated.
_skipped() {
    local lane=$1 entry
    for entry in $(printf '%s' "${VERIFY_SKIP:-}" | tr ',' ' '); do
        [ "$entry" = "$lane" ] && return 0
    done
    return 1
}

_fail_block() {
    local lane=$1 elapsed=$2 log=$3
    printf '\n  \xe2\x9c\x97 verify:%s failed (after %ss)\n\n' "$lane" "$elapsed"
    printf '    reproduce:  %s %s\n' "$SELF" "$lane"
    printf '    bypass:     VERIFY_SKIP=%s git push\n' "$lane"
    printf '                SKIP_VERIFY=1 git push          # skip every lane\n'
    printf '                git push --no-verify            # skip the hook entirely\n'
    printf '    logs:       %s\n\n' "$log"
}

# One row per invocation. `result` is PASS, FAIL, TIMEOUT or ABORT; `note` is written verbatim,
# so a caller says `failed:pytest` or `timeout:pytest` and the reader can tell them apart.
_log_summary() {
    local hook=$1 lanes=$2 result=$3 elapsed=$4 note=${5:-}
    mkdir -p "$(dirname "$LOG_SUMMARY")"
    if [ -n "$note" ]; then
        printf '%s | %-10s | %s | %s | %ss | %s\n' \
            "$(date '+%Y-%m-%d %H:%M:%S')" "$hook" "$lanes" "$result" "$elapsed" "$note" \
            >>"$LOG_SUMMARY"
    else
        printf '%s | %-10s | %s | %s | %ss\n' \
            "$(date '+%Y-%m-%d %H:%M:%S')" "$hook" "$lanes" "$result" "$elapsed" \
            >>"$LOG_SUMMARY"
    fi
}

# The row for a run that finished on its own. A timed-out one already has its row: the watchdog
# wrote it before signalling, so a shell that dies with the group cannot lose it.
_log_run() {
    local rc=$1
    [ "$rc" -eq "$EXIT_TIMEOUT" ] && return 0
    _log_summary "$HOOK" "$RUN_LANES" "$([ "$rc" -eq 0 ] && echo PASS || echo FAIL)" \
        "$(( $(date +%s) - RUN_START ))" "${_FAILED_LANES:+failed:$_FAILED_LANES}"
}

# --------------------------------------------------------------------------- deadline

# The process group of a backgrounded job, or nothing when ps cannot say.
_pgid_of() {
    local pgid
    pgid="$(ps -o pgid= -p "$1" 2>/dev/null | tr -d ' ')"
    case "$pgid" in
        ''|*[!0-9]*) return 1 ;;
        *) printf '%s' "$pgid" ;;
    esac
}

readonly MY_PGID="$(_pgid_of $$)"

# Signals a whole process group. Refuses a malformed id and refuses this shell's own group,
# which would take the git push above us down with it.
_signal_group() {
    local sig=$1 pgid=$2
    case "$pgid" in
        ''|*[!0-9]*) return 1 ;;
    esac
    [ "$pgid" = "${MY_PGID:-}" ] && return 1
    kill "-$sig" "-$pgid" 2>/dev/null
    return 0
}

# TERM, then KILL whatever ignored it. The group, never the single child: killing the direct
# child is what left a pytest running under PID 1 after git push, lefthook and this script had
# all exited (2026-08-15) — its own children never saw the signal.
_kill_group() {
    _signal_group TERM "$1" || return 0
    sleep 3
    _signal_group KILL "$1"
}

# Fires once per run, DEADLINE seconds in. Writes the summary row BEFORE it signals, because the
# shell may not survive to write one: that row is the only record a hung run leaves, and
# _log_summary is otherwise reached only after run_lanes returns.
_watchdog() {
    local hook=$1 lanes=$2 lane pgid
    sleep "$DEADLINE"
    lane="$(cat "$LOG_DIR/current-lane" 2>/dev/null)"
    pgid="$(cat "$LOG_DIR/current-pgid" 2>/dev/null)"
    : >"$LOG_DIR/timed-out"
    printf '\n  \xe2\x9c\x97 %-14s TIMEOUT after %ss\n' "${lane:-?}" "$DEADLINE"
    _log_summary "$hook" "$lanes" "TIMEOUT" "$DEADLINE" "timeout:${lane:-?}"
    _kill_group "$pgid"
}

# An operator's Ctrl-C is the other way a run ends with no row. Same order as the watchdog:
# write first, then take the lane's group down rather than leaving it behind.
_on_signal() {
    trap - INT TERM
    local lane pgid
    lane="$(cat "$LOG_DIR/current-lane" 2>/dev/null)"
    pgid="$(cat "$LOG_DIR/current-pgid" 2>/dev/null)"
    # Before anything else: an armed watchdog outlives this shell, holds its stdout open for the
    # rest of the deadline, and then fires against a process group that is long gone.
    _signal_group TERM "$(cat "$LOG_DIR/watchdog-pgid" 2>/dev/null)"
    printf '\n  interrupted (%s)%s\n' "$1" "${lane:+ during $lane}"
    _log_summary "$HOOK" "$RUN_LANES" "ABORT" "$(( $(date +%s) - RUN_START ))" \
        "signal:$1 ${lane:-none}"
    # Job control makes the shell announce every job it reaps on the way out ("Terminated: 15
    # lane_cmd ..."), which reads as an error the operator caused rather than the one they asked
    # for. Nothing after this point has anything of its own to say.
    exec 2>/dev/null
    _kill_group "$pgid"
    exit 130
}

# --------------------------------------------------------------------------- lanes

lane_cmd() {
    case "$1" in
        version-sync)  "$PY" tooling/version_sync.py --check ;;
        index)         "$PY" tooling/index_build.py --check ;;
        plugin-skills) "$PY" tooling/sync_plugin_skills.py --check ;;
        deps)          "$PY" gates/deps_guard.py ;;
        docs)          lane_docs ;;
        release)       "$PY" gates/release_guard.py ;;
        paths)         "$PY" gates/shipped_paths_guard.py ;;
        workflows)     "$PY" gates/workflow_lint.py ;;
        validate)      lane_validate ;;
        scaffold)      "$PY" gates/scaffold_freshness_guard.py ;;
        journey)       "$PY" gates/consumer_journey.py ;;
        tdd)           lane_tdd ;;
        js)            lane_js ;;
        pi-ts)         lane_pi_ts ;;
        pylint)        lane_pylint ;;
        pytest)        "$PY" -m pytest -q ;;
        mutation)      lane_mutation ;;
        *)             printf 'unknown lane: %s\n' "$1" >&2; return 2 ;;
    esac
}

# Three checks, one concern: the framework tree and the agent-instruction files that describe it
# must both validate. The two .mjs validators ran in no gate at all before 0.91.0 (review A7) —
# only their unit tests did, so real drift between model.json and CLAUDE.md reached main unseen.
readonly AGENT_INSTRUCTION_SCRIPTS="features/common/skills/maintain-agent-instructions/scripts"

lane_validate() {
    local rc=0 script
    "$PY" tooling/validate.py --all || rc=1
    for script in validate-agent-instructions.mjs check-agent-drift.mjs; do
        node "$AGENT_INSTRUCTION_SCRIPTS/$script" || rc=1
    done
    return "$rc"
}

# Two checks, one concern: the docs must describe the tree they ship with. docs_guard answers
# "does every reference resolve", changelog_index --check answers "is the generated release table
# still the one the entry files imply" (issue #160). Both run; the lane fails if either does.
lane_docs() {
    local rc=0
    "$PY" gates/docs_guard.py || rc=1
    "$PY" tooling/changelog_index.py --check || rc=1
    return "$rc"
}

# Mirrors CI: non-test Python only, 10.00 required. An empty file list means the index is
# wrong, not that the tree is clean, so it fails rather than reporting a 0s pass.
# `-j 0` fans out over every core, same verdict as serial.
lane_pylint() {
    local files
    files="$(git ls-files '*.py' | grep -v '^tests/')"
    if [ -z "$files" ]; then
        printf 'no non-test *.py files in the index; refusing to report a pass\n' >&2
        return 1
    fi
    # shellcheck disable=SC2086
    "$PY" -m pylint -j 0 $files
}

# node's own glob would expand to nothing and still exit 0 if the suite moved.
lane_js() {
    local files
    files="$(git ls-files 'tests/js/*.test.mjs')"
    if [ -z "$files" ]; then
        printf 'no tests/js/*.test.mjs in the index; refusing to report a pass\n' >&2
        return 1
    fi
    # shellcheck disable=SC2086
    node --test $files
}

# The pi adapter's TypeScript suite (bus push delivery, 0.159.0): bun unit tests over the
# adapter modules plus the type check. The adapter is the single arming point for pi's
# hooks (ADR-0022) and now carries the delivery state machine — an un-gated regression
# here ships silently (impl-review blocker B-1: 1430 test lines wired to no gate). Bun is
# the runner because that is what features/pi's toolchain standardizes on; production pi
# executes under Node, which is why the type check runs too (runtime drift the tests
# cannot see). Needs network on first run (bun install) — the CI gates job provisions bun.
lane_pi_ts() {
    command -v bun >/dev/null 2>&1 || {
        printf 'lane pi-ts: bun not found on PATH — install it (https://bun.sh) or run this lane where it exists\n' >&2
        return 1
    }
    (cd features/pi && bun install --frozen-lockfile >/dev/null 2>&1 \
        && bun test . \
        && bunx tsc --noEmit -p .)
}

# Mutation testing over features/common/retrieval/ only (see [tool.mutmut] in pyproject.toml
# and CONTRIBUTING.md). Deliberately not in $LANES: no score, no threshold, nothing here can
# fail a push — it is a review aid, run by hand as `verify.sh mutation`. `mutmut run` itself
# exits 0 with survivors still on the board; a non-zero exit means setup broke, not that a
# mutant survived.
lane_mutation() {
    "$PY" -c "import mutmut" >/dev/null 2>&1 || {
        printf 'mutmut not installed: %s -m pip install -r requirements-mutation.txt\n' "$PY" >&2
        return 1
    }
    # also_copy in [tool.mutmut] copies a lone file (.ai-badger/mcp-tools.yaml); mutmut only
    # creates parent directories for a directory also_copy entry (shutil.copytree), not a file
    # one (shutil.copy2), so the one file entry needs its directory made ahead of time.
    mkdir -p mutants/.ai-badger
    "$PY" -m mutmut run
    local rc=$?
    "$PY" -m mutmut results
    return "$rc"
}

# tdd_guard compares against the base branch, so that ref must exist locally.
lane_tdd() {
    git rev-parse --verify --quiet "$BASE_REF" >/dev/null || {
        printf 'base ref %s is missing; fetch it before running the tdd lane\n' "$BASE_REF" >&2
        return 1
    }
    "$PY" gates/tdd_guard.py --base "$BASE_REF"
}

# Runs one lane, captures its log, and prints the failure block. Returns the lane's verdict,
# or EXIT_TIMEOUT when the watchdog ended it — read off the marker file, never inferred from
# the 143 a lane can just as well exit with on its own.
run_lane() {
    local lane=$1 start elapsed log rc lane_pid
    if _skipped "$lane"; then
        printf '  \xe2\x88\x92 %-14s skipped (VERIFY_SKIP)\n' "$lane"
        return 0
    fi
    mkdir -p "$LOG_DIR"
    log="$LOG_DIR/$lane.log"
    start=$(date +%s)
    # Job control gives the lane a process group of its own, so the watchdog can take down
    # everything it spawned without signalling this shell or the git push above it.
    set -m
    lane_cmd "$lane" >"$log" 2>&1 &
    lane_pid=$!
    set +m
    _pgid_of "$lane_pid" >"$LOG_DIR/current-pgid"
    wait "$lane_pid" 2>/dev/null
    rc=$?
    : >"$LOG_DIR/current-pgid"
    elapsed=$(( $(date +%s) - start ))
    if [ -f "$LOG_DIR/timed-out" ]; then
        sed 's/^/      /' "$log"
        printf '\n    the %ss deadline ended this lane; no check failed.\n' "$DEADLINE"
        printf '    logs:       %s\n' "$log"
        printf '    raise it:   VERIFY_DEADLINE=%s git push\n' "$(( DEADLINE * 4 ))"
        printf '    bypass:     VERIFY_SKIP=%s git push\n\n' "$lane"
        return "$EXIT_TIMEOUT"
    fi
    if [ "$rc" -eq 0 ]; then
        printf '  \xe2\x9c\x93 %-14s %ss\n' "$lane" "$elapsed"
        return 0
    fi
    printf '  \xe2\x9c\x97 %-14s %ss\n' "$lane" "$elapsed"
    sed 's/^/      /' "$log"
    _fail_block "$lane" "$elapsed" "$log"
    return 1
}

# Runs the named lanes and returns non-zero if any failed. Never swallows a verdict.
# Sets _FAILED_LANES for callers that need the names (e.g. _log_summary).
# One watchdog for the whole run, not one per lane: DEADLINE bounds the push, and the lane it
# names comes from the file this loop keeps current.
run_lanes() {
    local lane failed="" rc dog_pid dog_pgid
    _FAILED_LANES=""
    mkdir -p "$LOG_DIR"
    rm -f "$LOG_DIR/timed-out"
    RUN_START=$(date +%s)
    RUN_LANES="$*"
    set -m
    _watchdog "$HOOK" "$RUN_LANES" &
    dog_pid=$!
    set +m
    dog_pgid="$(_pgid_of "$dog_pid")"
    printf '%s' "$dog_pgid" >"$LOG_DIR/watchdog-pgid"
    for lane in $@; do
        printf '%s' "$lane" >"$LOG_DIR/current-lane"
        run_lane "$lane"; rc=$?
        [ "$rc" -eq "$EXIT_TIMEOUT" ] && return "$EXIT_TIMEOUT"
        [ "$rc" -eq 0 ] || failed="$failed $lane"
    done
    # Its own group, so the watchdog's sleep dies with it instead of lingering as exactly the
    # kind of orphan this mechanism exists to prevent.
    _signal_group TERM "$dog_pgid"
    : >"$LOG_DIR/watchdog-pgid"
    printf '\n'
    if [ -n "$failed" ]; then
        _FAILED_LANES="$failed"
        printf 'FAILED after %ss:%s\n' "$(( $(date +%s) - RUN_START ))" "$failed"
        return 1
    fi
    printf 'ok - all lanes passed (%ss)\n' "$(( $(date +%s) - RUN_START ))"
    return 0
}

# --------------------------------------------------------------------------- change detection

# True when every ref on git's pre-push stdin (<local ref> <local sha> <remote ref> <remote sha>)
# is a branch deletion — an all-zero local sha. No stdin at all is a hand-run, not a deletion.
# The only routing left; why the rest went is in docs/changelog/0.123.0-*.md.
_deletion_only() {
    local lref lsha rref rsha lines=0 refs=0
    while read -r lref lsha rref rsha; do
        [ -n "${lref:-}" ] || continue
        lines=1
        case "$lsha" in
            *[!0]*) refs=1 ;;
        esac
    done
    [ "$lines" -eq 1 ] && [ "$refs" -eq 0 ]
}

# --------------------------------------------------------------------------- selection

# Prints the space-separated lanes `pre-push` would run, or the word DELETION.
# Consumes stdin, so it runs exactly once per invocation.
_select_lanes() {
    if _deletion_only; then
        printf 'DELETION\n'
        return 0
    fi
    printf '%s\n' "$LOCAL_LANES"
}

# --------------------------------------------------------------------------- doctor

# A hook counts as effective when it runs the needle directly or delegates to something
# that does; grepping for one marker cries wolf after another manager installs itself.
_hook_effective() {
    local hook_file=$1 needle=$2
    [ -f "$hook_file" ] || return 1
    grep -q "$needle" "$hook_file"
}

doctor() {
    local rc=0 hooks
    hooks="$(git rev-parse --path-format=absolute --git-common-dir)/hooks"
    printf 'repo          %s\n' "$PWD"
    printf 'self          %s\n' "$SELF"
    printf 'python        %s\n' "${PY:-<none found>}"

    if [ -z "${PY:-}" ] || [ ! -x "$PY" ]; then
        printf '  FAIL        no usable python3\n'; rc=1
    else
        printf '  version     %s\n' "$("$PY" --version 2>&1)"
        local mod
        for mod in pytest pylint jsonschema; do
            if "$PY" -c "import $mod" >/dev/null 2>&1; then
                printf '  ok          %s importable\n' "$mod"
            else
                printf '  FAIL        %s not importable by that interpreter\n' "$mod"; rc=1
            fi
        done
    fi

    if command -v node >/dev/null 2>&1; then
        printf 'node          %s\n' "$(node --version)"
    else
        printf 'node          FAIL not on PATH (js lane cannot run)\n'; rc=1
    fi

    if command -v lefthook >/dev/null 2>&1; then
        printf 'lefthook      %s\n' "$(lefthook version 2>&1)"
    else
        printf 'lefthook      not installed (gate will not fire on push)\n'
    fi

    printf 'hooks dir     %s\n' "$hooks"
    if _hook_effective "$hooks/pre-push" lefthook; then
        printf '  ok          pre-push delegates to lefthook\n'
    else
        printf '  WARN        pre-push is not lefthook; run `lefthook install`\n'
    fi
    if _hook_effective "$hooks/pre-commit" pre_commit; then
        printf '  ok          pre-commit still runs the pre-commit framework\n'
    else
        printf '  WARN        pre-commit no longer runs the pre-commit framework\n'
    fi
    if [ -f "$hooks/pre-commit.legacy" ]; then
        printf '  ok          pre-commit.legacy (code-review-graph) present\n'
    fi
    if [ -e "$hooks/pre-commit.old" ] || [ -e "$hooks/pre-push.old" ]; then
        printf '  FAIL        a .old hook exists: lefthook displaced a hook that no longer runs\n'
        rc=1
    fi

    local hookspath
    hookspath="$(git config --get core.hooksPath || true)"
    if [ -n "$hookspath" ]; then
        printf '  WARN        core.hooksPath=%s overrides .git/hooks\n' "$hookspath"
    fi

    if [ "$rc" -eq 0 ]; then
        printf '\nok - environment can run every lane\n'
    else
        printf '\nFAILED - see the FAIL lines above\n'
    fi
    return "$rc"
}

# --------------------------------------------------------------------------- entry

usage() {
    printf 'usage: %s <subcommand>\n\n' "$SELF"
    printf '  pre-push     the local lanes; a branch deletion runs none (reads pre-push stdin)\n'
    printf '  lanes        print what pre-push would run, without running it\n'
    printf '  all          every lane, including the ones a push leaves to CI\n'
    printf '  doctor       environment and hook integrity\n'
    printf '  <lane>       one of: %s\n' "$LANES"
    printf '               of those, %s run in CI on every push and not in the local hook\n' \
        "$CI_ONLY_LANES"
    printf '  mutation     features/common/retrieval/ only; never in the lanes above, run by hand\n\n'
    printf '  env: VERIFY_SKIP=lane[,lane]  SKIP_VERIFY=1  VERIFY_BASE=<ref>  AIB_PYTHON=<path>\n'
    printf '       VERIFY_DEADLINE=<seconds>   whole-gate wall clock, default %s; exit %s\n' \
        "$DEADLINE" "$EXIT_TIMEOUT"
}

main() {
    local cmd="${1:-}" lanes
    trap '_on_signal INT' INT
    trap '_on_signal TERM' TERM
    case "$cmd" in
        ""|-h|--help|help) usage; return 0 ;;
        doctor) doctor; return $? ;;
        all)
            printf '\xe2\x96\xb8 verify all\n'
            local rc
            HOOK="all"
            run_lanes "$LANES"; rc=$?
            _log_run "$rc"
            return $rc ;;
        lanes)
            _select_lanes; return $? ;;
        pre-push)
            # Before change detection, not after: a Ctrl-C during it must still name the hook.
            HOOK="pre-push"
            if [ -n "${SKIP_VERIFY:-}" ]; then
                printf 'verify: skipped (SKIP_VERIFY=%s)\n' "$SKIP_VERIFY"
                return 0
            fi
            lanes="$(_select_lanes)"
            case "$lanes" in
                DELETION) printf 'verify: branch deletion only, nothing to verify\n'; return 0 ;;
                "")       printf 'verify: nothing to verify\n'; return 0 ;;
            esac
            printf '\xe2\x96\xb8 verify pre-push: %s\n' "$lanes"
            local rc
            run_lanes "$lanes"; rc=$?
            _log_run "$rc"
            return $rc ;;
        *)
            # "mutation" is invocable by hand without joining $LANES (and therefore without
            # ever running via `all` or `pre-push`) — see lane_mutation above.
            case " $LANES mutation " in
                *" $cmd "*)
                    local rc
                    HOOK="lane"
                    run_lanes "$cmd"; rc=$?
                    _log_run "$rc"
                    return $rc ;;
                *) printf 'unknown subcommand: %s\n\n' "$cmd" >&2; usage >&2; return 2 ;;
            esac ;;
    esac
}

main "$@"
