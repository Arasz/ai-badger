# usage: sources.sh <root>; rtk rewrite exit codes per ask-rule source, plain and RTK_REWRITE_HOST=openclaw
R=$1; mkdir -p $R
ask='{"permissions":{"ask":["Bash(git push:*)"]}}'
fresh() { B=$(mktemp -d "$R/case.XXXX"); mkdir -p $B/p/.claude $B/p/sub $B/home/.claude; git -C $B/p init -q; }
code() { (cd "$1" && HOME=$B/home RTK_DB_PATH=$B/db RTK_TELEMETRY_DISABLED=1 RTK_RECALL=0 $2 rtk rewrite "git push origin main" >/dev/null 2>&1; echo $?); }
run() { echo "$1: plain=$(code $B/${2:-p} 'env -u RTK_REWRITE_HOST') openclaw=$(code $B/${2:-p} 'env RTK_REWRITE_HOST=openclaw')"; }
fresh; run "no rules"
fresh; echo "$ask" > $B/p/.claude/settings.json; run "ask in project settings.json"
fresh; echo "$ask" > $B/p/.claude/settings.local.json; run "ask in project settings.local.json"
fresh; echo "$ask" > $B/home/.claude/settings.json; run "ask in user ~/.claude/settings.json"
fresh; echo "$ask" > $B/p/.claude/settings.json; run "ask in project, cwd=subdir" p/sub
fresh; echo '{"permissions":{"allow":["Bash"],"ask":["Bash(git push:*)"]}}' > $B/p/.claude/settings.json; run "broad allow + ask"
fresh; echo '{"permissions":{"allow":["Bash"]}}' > $B/p/.claude/settings.json; run "broad allow only"
fresh; echo '{"permissions":{"allow":["Bash(*)"]}}' > $B/p/.claude/settings.json; run "allow Bash(*) only"
fresh; echo '{"permissions":{"allow":["Bash(git push:*)"]}}' > $B/p/.claude/settings.json; run "allow Bash(git push:*) only"
fresh; echo '{"permissions":{"ask":["Bash(git push:*)"]}}' > $B/p/.claude/settings.json; echo "compound (ask in chain): $(cd $B/p && HOME=$B/home RTK_DB_PATH=$B/db RTK_REWRITE_HOST=openclaw rtk rewrite 'git status && git push origin main' 2>/dev/null; echo " exit=$?")"
