#!/bin/sh
# usage: runclaude.sh <outfile> <prompt>
cd "$R" && RTK_DB_PATH=$R/.rtkdb RTK_RECALL=0 claude -p --setting-sources project --model haiku --max-turns 3 --allowedTools Bash --output-format stream-json --verbose --no-session-persistence --strict-mcp-config "$2" > "$1" 2>&1 < /dev/null
echo "claude rc=$?"
