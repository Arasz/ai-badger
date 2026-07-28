#!/usr/bin/env bash
# ai-badger local quality gate. One subcommand per lane; `pre-push` selects lanes from
# the changed paths, `all` runs every lane, `doctor` checks the environment and hooks.
# Contract: exit 0 = pass, non-zero = fail. No other exit code means anything.
# Targets bash 3.2 (macOS system bash): no associative arrays, no ${var,,}.
set -uo pipefail

_self_abs="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
cd "$(git rev-parse --show-toplevel)" || exit 1
readonly SELF="${_self_abs#"$PWD"/}"

# git exports these to a hook and they point a child's git at THIS repo, so a test building a
# throwaway repo would write to the real one. Dropped after the cd, so a lane sees the same
# environment it would see when run by hand.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX GIT_QUARANTINE_PATH \
      GIT_REFLOG_ACTION GIT_AUTHOR_DATE GIT_COMMITTER_DATE GIT_EDITOR

# Keyed by checkout: the pytest lane runs this script in a throwaway repo, and a shared path
# would let that nested run overwrite the log the failure block just cited.
_log_key="$(printf '%s' "$PWD" | cksum | cut -d' ' -f1)"
readonly LOG_DIR="${VERIFY_LOG_DIR:-${TMPDIR:-/tmp}/ai-badger-verify/$_log_key}"
readonly BASE_REF="${VERIFY_BASE:-origin/main}"
readonly LOG_SUMMARY="logs/lefthook.log"

# Cheap lanes first so a typo fails fast, before pylint and pytest.
readonly LANES="version-sync index plugin-skills deps docs release validate tdd js pylint pytest"

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

_log_summary() {
    local hook=$1 lanes=$2 result=$3 elapsed=$4 failed=${5:-}
    mkdir -p "$(dirname "$LOG_SUMMARY")"
    if [ -n "$failed" ]; then
        printf '%s | %-10s | %s | %s | %ss | failed:%s\n' \
            "$(date '+%Y-%m-%d %H:%M:%S')" "$hook" "$lanes" "$result" "$elapsed" "$failed" \
            >>"$LOG_SUMMARY"
    else
        printf '%s | %-10s | %s | %s | %ss\n' \
            "$(date '+%Y-%m-%d %H:%M:%S')" "$hook" "$lanes" "$result" "$elapsed" \
            >>"$LOG_SUMMARY"
    fi
}

# --------------------------------------------------------------------------- lanes

lane_cmd() {
    case "$1" in
        version-sync)  "$PY" scripts/version_sync.py --check ;;
        index)         "$PY" scripts/index_build.py --check ;;
        plugin-skills) "$PY" scripts/sync_plugin_skills.py --check ;;
        deps)          "$PY" gates/deps_guard.py ;;
        docs)          "$PY" gates/docs_guard.py ;;
        release)       "$PY" gates/release_guard.py ;;
        validate)      "$PY" scripts/validate.py --all ;;
        tdd)           lane_tdd ;;
        js)            lane_js ;;
        pylint)        lane_pylint ;;
        pytest)        "$PY" -m pytest -q ;;
        *)             printf 'unknown lane: %s\n' "$1" >&2; return 2 ;;
    esac
}

# Mirrors CI: non-test Python only, 10.00 required. An empty file list means the index is
# wrong, not that the tree is clean, so it fails rather than reporting a 0s pass.
lane_pylint() {
    local files
    files="$(git ls-files '*.py' | grep -v '^tests/')"
    if [ -z "$files" ]; then
        printf 'no non-test *.py files in the index; refusing to report a pass\n' >&2
        return 1
    fi
    # shellcheck disable=SC2086
    "$PY" -m pylint $files
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

# tdd_guard compares against the base branch, so that ref must exist locally.
lane_tdd() {
    git rev-parse --verify --quiet "$BASE_REF" >/dev/null || {
        printf 'base ref %s is missing; fetch it before running the tdd lane\n' "$BASE_REF" >&2
        return 1
    }
    "$PY" gates/tdd_guard.py --base "$BASE_REF"
}

# Runs one lane, captures its log, and prints the failure block. Returns the lane's verdict.
run_lane() {
    local lane=$1 start elapsed log
    if _skipped "$lane"; then
        printf '  \xe2\x88\x92 %-14s skipped (VERIFY_SKIP)\n' "$lane"
        return 0
    fi
    mkdir -p "$LOG_DIR"
    log="$LOG_DIR/$lane.log"
    start=$(date +%s)
    if lane_cmd "$lane" >"$log" 2>&1; then
        printf '  \xe2\x9c\x93 %-14s %ss\n' "$lane" "$(( $(date +%s) - start ))"
        return 0
    fi
    elapsed=$(( $(date +%s) - start ))
    printf '  \xe2\x9c\x97 %-14s %ss\n' "$lane" "$elapsed"
    sed 's/^/      /' "$log"
    _fail_block "$lane" "$elapsed" "$log"
    return 1
}

# Runs the named lanes and returns non-zero if any failed. Never swallows a verdict.
# Sets _FAILED_LANES for callers that need the names (e.g. _log_summary).
run_lanes() {
    local lane failed="" start
    _FAILED_LANES=""
    start=$(date +%s)
    for lane in $@; do
        run_lane "$lane" || failed="$failed $lane"
    done
    printf '\n'
    if [ -n "$failed" ]; then
        _FAILED_LANES="$failed"
        printf 'FAILED after %ss:%s\n' "$(( $(date +%s) - start ))" "$failed"
        return 1
    fi
    printf 'ok - all lanes passed (%ss)\n' "$(( $(date +%s) - start ))"
    return 0
}

# --------------------------------------------------------------------------- change detection

# Emits the paths this push would publish. Reads git's pre-push stdin protocol
# (<local ref> <local sha> <remote ref> <remote sha>); falls back to the merge base
# with BASE_REF when invoked by hand with no stdin.
# Returns 3 when every ref on stdin was a deletion, which is not the same as no stdin:
# a deletion publishes no content, so the gate must run nothing rather than everything.
_changed_paths() {
    local lref lsha rref rsha lines=0 refs=0 base
    while read -r lref lsha rref rsha; do
        [ -n "${lref:-}" ] || continue
        lines=1
        case "$lsha" in
            *[!0]*) ;;
            *) continue ;;   # all-zero local sha: branch deletion
        esac
        refs=1
        case "${rsha:-}" in
            *[!0]*) git diff --name-only "$rsha" "$lsha" ;;
            *) base="$(git merge-base "$BASE_REF" "$lsha" 2>/dev/null)"
               if [ -n "$base" ]; then
                   git diff --name-only "$base" "$lsha"
               else
                   git diff --name-only "$(git hash-object -t tree /dev/null)" "$lsha"
               fi ;;
        esac
    done
    if [ "$lines" -eq 1 ] && [ "$refs" -eq 0 ]; then
        return 3
    fi
    if [ "$lines" -eq 0 ]; then
        base="$(git merge-base "$BASE_REF" HEAD 2>/dev/null)"
        [ -n "$base" ] && git diff --name-only "$base" HEAD
        git diff --name-only HEAD
    fi
    return 0
}

# Maps changed paths to the lanes that can see them. The gate's own files, and CI's,
# route to run-everything: a broken gate is invisible until something stops being verified.
_lanes_for() {
    local path want_all=0 py=0 mjs=0 md=0 json=0 any=0
    while read -r path; do
        [ -n "$path" ] || continue
        any=1
        case "$path" in
            .github/workflows/*|.lefthook/*|lefthook.yml) want_all=1 ;;
            *.mjs)  mjs=1 ;;
            *.py)   py=1 ;;
            *.md)   md=1 ;;
            *.json|schemas/*|VERSION) json=1 ;;
            *)      json=1 ;;
        esac
    done
    if [ "$want_all" -eq 1 ] || [ "$any" -eq 0 ]; then
        printf '%s\n' "$LANES"
        return 0
    fi
    # The whole-tree guards are seconds each and catch cross-file breakage, so they always run.
    local lanes="version-sync index plugin-skills deps docs release validate tdd"
    [ "$mjs" -eq 1 ] && lanes="$lanes js"
    [ "$py" -eq 1 ] && lanes="$lanes pylint pytest"
    [ "$json" -eq 1 ] && lanes="$lanes pytest"
    [ "$md" -eq 1 ] && lanes="$lanes"
    printf '%s\n' "$lanes" | tr ' ' '\n' | awk 'NF && !seen[$0]++' | tr '\n' ' '
    printf '\n'
}

# Prints the space-separated lanes `pre-push` would run, or the word DELETION.
# Consumes stdin, so it runs exactly once per invocation.
_select_lanes() {
    local changed rc
    mkdir -p "$LOG_DIR"
    changed="$LOG_DIR/changed-paths.txt"
    _changed_paths >"$changed"
    rc=$?
    if [ "$rc" -eq 3 ]; then
        printf 'DELETION\n'
        return 0
    fi
    sort -u "$changed" | _lanes_for | sed 's/ *$//'
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
    printf '  pre-push     lanes selected from the changed paths (reads git pre-push stdin)\n'
    printf '  lanes        print what pre-push would run, without running it\n'
    printf '  all          every lane, no change detection\n'
    printf '  doctor       environment and hook integrity\n'
    printf '  <lane>       one of: %s\n\n' "$LANES"
    printf '  env: VERIFY_SKIP=lane[,lane]  SKIP_VERIFY=1  VERIFY_BASE=<ref>  AIB_PYTHON=<path>\n'
}

main() {
    local cmd="${1:-}" lanes
    case "$cmd" in
        ""|-h|--help|help) usage; return 0 ;;
        doctor) doctor; return $? ;;
        all)
            printf '\xe2\x96\xb8 verify all\n'
            local rc start
            start=$(date +%s)
            run_lanes "$LANES"; rc=$?
            _log_summary "all" "$LANES" "$([ $rc -eq 0 ] && echo PASS || echo FAIL)" "$(( $(date +%s) - start ))" "$_FAILED_LANES"
            return $rc ;;
        lanes)
            _select_lanes; return $? ;;
        pre-push)
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
            local rc start
            start=$(date +%s)
            run_lanes "$lanes"; rc=$?
            _log_summary "pre-push" "$lanes" "$([ $rc -eq 0 ] && echo PASS || echo FAIL)" "$(( $(date +%s) - start ))" "$_FAILED_LANES"
            return $rc ;;
        *)
            case " $LANES " in
                *" $cmd "*)
                    local rc start
                    start=$(date +%s)
                    run_lanes "$cmd"; rc=$?
                    _log_summary "lane" "$cmd" "$([ $rc -eq 0 ] && echo PASS || echo FAIL)" "$(( $(date +%s) - start ))" "$_FAILED_LANES"
                    return $rc ;;
                *) printf 'unknown subcommand: %s\n\n' "$cmd" >&2; usage >&2; return 2 ;;
            esac ;;
    esac
}

main "$@"
