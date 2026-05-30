#!/bin/zsh
# Install (or reinstall) the forecast-trigger LaunchAgent on a Mac Mini.
#
# Run this ON the Mini:
#   cd ops/macmini-trigger && zsh install.sh
#
# Idempotent: safe to re-run after editing the script or plist. Rewrites the
# reference plist's home paths to the current $HOME, so it works for any user.
#
# Prerequisite: gh installed and authed with the 'workflow' scope:
#   brew install gh
#   gh auth login --hostname github.com --git-protocol https --web --scopes workflow
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.imeteo.forecast-trigger"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_="$(id -u)"

# --- preflight: gh must be able to dispatch ---
if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh not found. Install it: brew install gh" >&2; exit 1
fi
if ! gh auth status 2>&1 | grep -q "workflow"; then
  echo "ERROR: gh token lacks 'workflow' scope. Run:" >&2
  echo "  gh auth login --hostname github.com --git-protocol https --web --scopes workflow" >&2
  exit 1
fi

mkdir -p "$HOME/bin" "$HOME/Library/Logs" "$HOME/Library/LaunchAgents"

# trigger script
install -m 0755 "$HERE/trigger-forecast.sh" "$HOME/bin/trigger-forecast.sh"

# plist, with paths rewritten to this machine's $HOME
sed "s|/Users/lubomirfranko|$HOME|g" \
  "$HERE/$LABEL.plist" > "$PLIST"
chmod 0644 "$PLIST"
plutil -lint "$PLIST"

# (re)load
launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_" "$PLIST"

if launchctl list | grep -q "$LABEL"; then
  echo "OK: $LABEL installed and loaded (fires at :15 and :45)."
  echo "Test now: ~/bin/trigger-forecast.sh && gh run list -R imeteo-data/imeteo-icon-ruc -L3"
else
  echo "ERROR: agent did not load." >&2; exit 1
fi
