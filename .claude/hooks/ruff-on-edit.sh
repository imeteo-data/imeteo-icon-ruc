#!/usr/bin/env bash
# PostToolUse hook — run ruff on Python files Claude edits.
#
# Triggered after Edit/Write on any file. If the file is a .py under
# pipeline/, tests/, scripts/, or the root *.py, run `ruff check --fix` + `ruff format` on it
# and print the result so Claude sees it in the session.
#
# Receives the tool call as JSON on stdin:
#   {"tool_name": "Edit", "tool_input": {"file_path": "...", ...}, ...}
#
# Exits 0 in all cases (the hook is informational, not a gate — CI is
# the gate). On violations, ruff's output is printed and Claude picks
# it up from the tool result stream.

set -u

# Read and parse the file_path from the JSON on stdin.
input="$(cat)"
file_path="$(printf '%s' "$input" | python3 -c 'import json, sys; d=json.load(sys.stdin); print(d.get("tool_input", {}).get("file_path", ""))' 2>/dev/null)"

# Skip: no path, not a .py file, not under a linted dir
[ -z "$file_path" ] && exit 0
case "$file_path" in
    *.py) ;;
    *) exit 0 ;;
esac
case "$file_path" in
    */pipeline/*|*/tests/*|*/scripts/*) ;;
    pipeline/*|tests/*|scripts/*) ;;
    */api.py|*/cleanup.py|*/main.py) ;;
    *) exit 0 ;;
esac

# Skip files that don't exist (e.g., Edit on a just-deleted file)
[ -f "$file_path" ] || exit 0

# Run ruff from the repo root (owns pyproject.toml); CI uses `uvx ruff`.
top=$(git -C "$(dirname "$file_path")" rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$top" || exit 0
ruff_cmd=(uvx ruff)
fix_output="$("${ruff_cmd[@]}" check --fix --force-exclude "$file_path" 2>&1)"
fix_rc=$?
format_output="$("${ruff_cmd[@]}" format --force-exclude "$file_path" 2>&1)"
format_rc=$?

if [ $fix_rc -ne 0 ] || [ $format_rc -ne 0 ] || [ -n "$fix_output" ]; then
    echo "── ruff on $file_path ──"
    [ -n "$fix_output" ] && echo "$fix_output"
    [ -n "$format_output" ] && echo "$format_output"
fi

exit 0
