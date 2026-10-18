# usage: run.sh <name> <hook> <ask> <command>
D=/private/tmp/claude-501/-Users-arasz-RiderProjects-ai-badger/29c16558-6b9d-41c5-ace9-22a75c4cdd1c/scratchpad/askfix
S=/private/tmp/claude-501/-Users-arasz-RiderProjects-ai-badger/29c16558-6b9d-41c5-ace9-22a75c4cdd1c/scratchpad/s13
PY=/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3
before=$(shasum ~/.claude/settings.json | cut -c1-12 | tr '\n' ' ')
$PY $D/case.py "$1" "$2" "$3"
R=$S/R sh $S/runclaude.sh $D/$1.jsonl "Run exactly this one command and nothing else: $4" >/dev/null
after=$(shasum ~/.claude/settings.json | cut -c1-12 | tr '\n' ' ')
head=$(git --git-dir=$D/$1.remote.git rev-parse -q --verify main 2>/dev/null || echo NONE)
denials=$($PY -c "import json,sys
for l in open(sys.argv[1]):
    try: e=json.loads(l)
    except Exception: continue
    if e.get('type')=='result': print(len(e.get('permission_denials',[])))" $D/$1.jsonl)
echo "$1 hook=$2 ask=$3 | remote main=${head:0:8} | executed=$(cat $D/$1.post.jsonl | $PY -c 'import json,sys;print([json.loads(l)["command"] for l in sys.stdin])') | denials=$denials | home $( [ "$before" = "$after" ] && echo unchanged || echo CHANGED)"
