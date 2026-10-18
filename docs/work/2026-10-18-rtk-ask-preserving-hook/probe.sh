T=$(mktemp -d); export RTK_DB_PATH=$T/db RTK_TELEMETRY_DISABLED=1 RTK_RECALL=0
while IFS= read -r c; do out=$(rtk rewrite "$c" 2>&1); printf "%s\t[%s]\t%s\n" "$c" "$?" "$out"; done < "$1"
