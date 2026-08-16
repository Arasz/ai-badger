#!/usr/bin/env bash
# Derive the facts a manual checklist run compares the running build against.
# Exits non-zero when a fact cannot be derived, so a missing path fails loudly
# instead of yielding a confident zero.
set -euo pipefail

repo_root="${1:-.}"
csproj="$repo_root/src/AiRaccoon/AiRaccoon.csproj"
tools_dir="$repo_root/src/AiRaccoon/Tools"
prompts_dir="$repo_root/src/AiRaccoon/Prompts"

fail() {
    echo "derive-facts: $1" >&2
    echo "derive-facts: the tree layout moved; fix this script rather than typing the fact by hand." >&2
    exit 1
}

[ -f "$csproj" ] || fail "no csproj at $csproj"
[ -d "$tools_dir" ] || fail "no tools directory at $tools_dir"
[ -d "$prompts_dir" ] || fail "no prompts directory at $prompts_dir"

version="$(sed -n 's/.*<PackageVersion>\(.*\)<\/PackageVersion>.*/\1/p' "$csproj" | head -n 1)"
[ -n "$version" ] && [ "$version" != '$(Version)' ] || fail "no literal <PackageVersion> in $csproj"

count_attribute() {
    # Matches whole lines first, not just occurrences, so a comment line can be dropped before
    # counting the per-line uses on what remains. A doc comment that names the attribute in
    # prose (McpToolInventory.cs's does, on purpose) would otherwise count as a use of it.
    local dir="$1" attribute="$2" total
    total="$(grep -rh "\[$attribute" --include='*.cs' "$dir" \
        | grep -v '^[[:space:]]*\(///\|//\|\*\)' \
        | grep -o "\[$attribute" | wc -l | tr -d ' ')"
    [ "$total" -gt 0 ] || fail "zero [$attribute] found under $dir"
    echo "$total"
}

tools="$(count_attribute "$tools_dir" McpServerTool)"
prompts="$(count_attribute "$prompts_dir" McpServerPrompt)"

cat <<EOF
version=$version
mcp-tool-count=$tools
mcp-prompt-count=$prompts
EOF

echo "derive-facts: copy these into the checklist's \"derived\" block verbatim." >&2
