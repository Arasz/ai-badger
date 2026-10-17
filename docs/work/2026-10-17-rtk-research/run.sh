#!/bin/bash
# Rerun one rtk-init experiment in a throwaway HOME and git repo; never touches the real HOME.
# usage: BASE=/tmp OUT=./outputs run.sh NAME -- <rtk init args...>
# e.g.   run.sh claude-l -- --auto-patch      run.sh pi-g -- -g --agent pi --auto-patch
set -u
name=$1; shift; shift
BASE=${BASE:-/tmp}; OUT=${OUT:-$BASE/rtkres}; mkdir -p "$OUT"
H=$BASE/rtkhome-$name; R=$BASE/rtkrepo-$name
rm -rf "$H" "$R"; mkdir -p "$H" "$R"
( cd "$R" && git init -q && echo "# repo" > README.md && git add . && git -c user.email=a@b -c user.name=x commit -qm init )
snap(){ (cd "$1" && find . -path ./.git -prune -o -type f -print | sort | while read -r f; do echo "$f $(shasum "$f" | cut -c1-12)"; done); }
export HOME=$H XDG_CONFIG_HOME=$H/.config XDG_DATA_HOME=$H/.local/share XDG_CACHE_HOME=$H/.cache CODEX_HOME=$H/.codex
unset RTK_TELEMETRY_DISABLED
cd "$R" || exit 1
echo "### run1: rtk init $*"; rtk init "$@" </dev/null; echo "EXIT1=$?"
snap "$H" > "$OUT/$name.h1"; snap "$R" > "$OUT/$name.r1"
echo "### run2"; rtk init "$@" </dev/null >"$OUT/$name.run2.out" 2>&1; echo "EXIT2=$?"
snap "$H" > "$OUT/$name.h2"; snap "$R" > "$OUT/$name.r2"
echo "### idempotency diff (home, repo):"; diff "$OUT/$name.h1" "$OUT/$name.h2"; diff "$OUT/$name.r1" "$OUT/$name.r2"
echo "### uninstall: rtk init $* --uninstall"; rtk init "$@" --uninstall </dev/null; echo "EXITU=$?"
snap "$H" > "$OUT/$name.hu"; snap "$R" > "$OUT/$name.ru"
