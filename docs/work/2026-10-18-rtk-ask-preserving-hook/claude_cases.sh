# usage: claude_cases.sh <rtk_guard.py> — Claude adapter cases in a temp repo with ask Bash(git push:*)
G=$1
R=$(mktemp -d); H=$(mktemp -d)
cd "$R" && git init -q && mkdir .claude
printf '%s' '{"permissions":{"ask":["Bash(git push:*)"]}}' > .claude/settings.json
run() {  # run <label> <expect: unchanged|rewrite|no-allow> <inherited RTK_REWRITE_HOST> <command>
  ev=$(python3 -c 'import json,sys;print(json.dumps({"tool_name":"Bash","cwd":sys.argv[1],"tool_input":{"command":sys.argv[2]}}))' "$R" "$4")
  out=$(printf '%s' "$ev" | env HOME="$H" RTK_TELEMETRY_DISABLED=1 RTK_DB_PATH="$H/t.db" RTK_REWRITE_HOST="$3" python3 "$G" claude)
  case "$2" in
    unchanged) [ -z "$out" ] && ok=PASS || ok=FAIL ;;
    rewrite) [ -n "$out" ] && ok=PASS || ok=FAIL ;;
    no-allow) echo "$out" | grep -q '"allow"' && ok=FAIL || ok=PASS ;;
  esac
  printf '%s\tclaude\t%s\t%s\t-> %s\n' "$ok" "$1" "$(printf '%s' "$4" | tr '\n' ';')" "${out:-(unchanged)}"
}
run "ask rule" unchanged "" "git push origin main"
run "no rule" rewrite "" "git status"
run "ask rule in chain" unchanged "" "git status && git push origin main"
run "ask rule on a second line" unchanged "" "$(printf 'git status\ngit push origin main')"
run "inherited RTK_REWRITE_HOST, no rule" no-allow openclaw "git status"
