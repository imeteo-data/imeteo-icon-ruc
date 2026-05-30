#!/bin/zsh
# Reliable trigger for the ICON-D2-RUC-EPS forecast pipeline.
#
# GitHub's scheduled `cron:` is best-effort and drops ~90% of fires (observed
# ~8/day against a requested 96/day). This LaunchAgent runs on the always-on
# Mac Mini (imeteo-data-dev-01) and dispatches the workflow on a dependable
# schedule instead. The workflow's own `--runs 12 --backfill` recovers any run
# that lands between fires, so exact timing here is not critical.
#
# Deployed copy lives at ~/bin/trigger-forecast.sh on the Mini. Paired plist:
#   ~/Library/LaunchAgents/com.imeteo.forecast-trigger.plist
# See README.md in this directory for the full architecture + reinstall steps.
PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
LOG="$HOME/Library/Logs/forecast-trigger.log"
TS=$(date -u +'%Y-%m-%dT%H:%M:%SZ')

gh workflow run forecast.yml -R imeteo-data/imeteo-icon-ruc >>"$LOG" 2>&1
RC=$?
if [ "$RC" -eq 0 ]; then
  echo "$TS  dispatched forecast.yml OK" >>"$LOG"
else
  echo "$TS  DISPATCH FAILED (gh exit $RC)" >>"$LOG"
fi

# keep the log bounded
tail -n 500 "$LOG" >"$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
