"""Fail when the committed forecast data has gone stale.

Freshness signal: `generated_at` in data/forecasts/index.json — the pipeline
rewrites it every time it commits new output, so its age measures how long
the whole trigger stack (Mac Mini dispatch loop + GitHub cron fallback) has
produced nothing. Run by .github/workflows/freshness.yml; also runnable
locally: `python3 .github/scripts/check_freshness.py`.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

MAX_AGE_HOURS = 2.0

INDEX = Path(__file__).resolve().parents[2] / "data" / "forecasts" / "index.json"


def main() -> int:
    try:
        generated_at = datetime.fromisoformat(json.loads(INDEX.read_text())["generated_at"])
    except (OSError, ValueError, KeyError) as e:
        print(f"::error::Cannot read generated_at from {INDEX}: {e}")
        return 1
    age_hours = (datetime.now(UTC) - generated_at).total_seconds() / 3600
    print(f"index.json generated_at={generated_at.isoformat()} (age {age_hours:.2f} h)")
    if age_hours > MAX_AGE_HOURS:
        print(
            f"::error::Forecast data is stale: last pipeline output {age_hours:.1f} h ago "
            f"(threshold {MAX_AGE_HOURS:g} h). Check the Mac Mini dispatch loop and the "
            f"Forecast & Deploy workflow."
        )
        return 1
    print(f"Fresh (threshold {MAX_AGE_HOURS:g} h).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
