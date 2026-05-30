# Mac Mini forecast trigger

Makes the forecast pipeline run **on a dependable schedule** by dispatching the
GitHub workflow from an always-on Mac Mini, instead of trusting GitHub's
scheduled `cron:` (which silently drops ~90% of fires).

## Why this exists

GitHub's `schedule:` trigger is best-effort with no SLA. Measured over ~62 h
against a `*/15` cron (96 fires/day requested), GitHub delivered only **~8.6
fires/day** — median gap **2.5 h**, never once the 15 min asked for. That is why
the dashboard could lag reality by hours. No change to the cron string fixes
this; the only fix is to dispatch from hardware we control.

## How it works — and the two fallback layers

The system is resilient to the Mac Mini going down at **both** layers. If the
Mini disappears, GitHub takes over automatically with no manual step.

### 1. Trigger (who kicks off a run)

| | Primary | Fallback (Mini down) |
|---|---|---|
| Source | Mac Mini LaunchAgent, fires **:15 & :45** | GitHub `*/15` cron in `forecast.yml` |
| Reliability | Dispatches every time | Best-effort (~8/day) |
| Freshness | ≤ ~30 min behind DWD | ≤ ~3 h behind DWD |

Both run simultaneously today; the redundant fires are cheap no-ops (the
workflow only commits/deploys when forecasts actually change). **Keep the GitHub
cron in `forecast.yml` — it *is* the trigger fallback. Do not remove it.**

### 2. Execution (where the job runs)

`choose-runner.yml` checks whether a self-hosted runner named `mac-mini-m2` is
online. If yes → run on the Mini (fast, has the Rust ext). If not → **fall back
to `ubuntu-latest`** (GitHub-hosted). As of 2026-05-30 no self-hosted runner is
registered, so execution already runs entirely on `ubuntu-latest`. The Mini
being down therefore has **zero** effect on execution.

### Completeness safety net

Whichever trigger fires, the pipeline runs `main.py --runs 12 --backfill`, which
reprocesses the latest 12 DWD runs and skips ones already complete. So any run
that lands between fires is recovered on the next fire, as long as *some* trigger
fires within DWD's ~24 h retention window — which the GitHub cron alone
satisfies. **Net effect of a Mini outage: freshness degrades from ~30 min to
~3 h; no data is lost.**

## What gets installed on the Mini

| Path | Purpose |
|---|---|
| `~/bin/trigger-forecast.sh` | runs `gh workflow run forecast.yml` |
| `~/Library/LaunchAgents/com.imeteo.forecast-trigger.plist` | schedules it at :15 and :45 |
| `~/Library/Logs/forecast-trigger.log` | dispatch log |

Requires `gh` authed with the `workflow` scope (token in `~/.config/gh`).

## Install / reinstall (e.g. after a Mini rebuild)

```bash
# prerequisites
brew install gh
gh auth login --hostname github.com --git-protocol https --web --scopes workflow

# install the agent
cd ops/macmini-trigger
zsh install.sh
```

`install.sh` is idempotent and rewrites the plist's home paths to the current
`$HOME`, so it works for any user account.

## Manage / verify

```bash
launchctl list | grep forecast-trigger          # loaded?
~/bin/trigger-forecast.sh                        # fire once now
tail ~/Library/Logs/forecast-trigger.log         # dispatch log
gh run list -R imeteo-data/imeteo-icon-ruc -L5   # confirm a run appeared

# reload after editing the plist
launchctl bootout gui/$(id -u)/com.imeteo.forecast-trigger
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.imeteo.forecast-trigger.plist

# disable entirely (revert to GitHub cron only)
launchctl bootout gui/$(id -u)/com.imeteo.forecast-trigger
```
