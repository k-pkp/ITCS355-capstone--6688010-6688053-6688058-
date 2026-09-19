"""Decide which stations are fit to train on, and record why the others are not.

    python scripts/screen_stations.py

Writes data/excluded_stations.json.

The exclusions are written to a file rather than applied silently inside the training
script. Three reasons. A reviewer can see what was dropped without reading code. The count
becomes a metric, so a fleet that is quietly degrading is visible. And a station that
recovers can be readmitted by re-running this, rather than by someone remembering that a
hard-coded list exists.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.airquality import quality

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
STATIONS_FILE = PROJECT_ROOT / "data" / "stations.json"
EXCLUSIONS_FILE = PROJECT_ROOT / "data" / "excluded_stations.json"


def parse_command_line() -> argparse.Namespace:
    """Command line for the station screen."""
    parser = argparse.ArgumentParser(description="Screen stations for training fitness")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--stations", type=Path, default=STATIONS_FILE)
    parser.add_argument("--out", type=Path, default=EXCLUSIONS_FILE)
    return parser.parse_args()


def load_readings(raw_dir: Path) -> pd.DataFrame:
    """Read every station file into one frame."""
    paths = sorted(raw_dir.glob("station-*.csv"))
    if not paths:
        raise SystemExit(f"no data in {raw_dir}; run `dvc pull` or the download script")

    frames = [pd.read_csv(path, parse_dates=["datetime_utc"]) for path in paths]
    return pd.concat(frames, ignore_index=True).sort_values(
        ["location_id", "datetime_utc"]
    )


def main() -> int:
    """Screen every pinned station and write the exclusions with their evidence."""
    options = parse_command_line()

    pinned = json.loads(options.stations.read_text())
    pinned_ids = {station["location_id"] for station in pinned["stations"]}
    readings = load_readings(options.raw_dir)

    exclusions = quality.screen_all(readings, pinned_ids)
    excluded_ids = quality.excluded_location_ids(exclusions)

    payload = {
        "screened_at_utc": datetime.now(timezone.utc).isoformat(),
        "pinned_stations": len(pinned_ids),
        "excluded_stations": len(excluded_ids),
        "usable_stations": len(pinned_ids) - len(excluded_ids),
        "thresholds": {
            "maximum_zero_rate": quality.MAXIMUM_ZERO_RATE,
            "maximum_flat_run_hours": quality.MAXIMUM_FLAT_RUN_HOURS,
        },
        "exclusions": [
            {
                "location_id": exclusion.location_id,
                "reason": exclusion.reason,
                "detail": exclusion.detail,
                "evidence": exclusion.evidence,
            }
            for exclusion in exclusions
        ],
    }

    options.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print(f"pinned   {len(pinned_ids)}")
    print(f"excluded {len(excluded_ids)}")
    print(f"usable   {payload['usable_stations']}\n")

    for exclusion in exclusions:
        print(f"  {exclusion}")

    print(f"\nwrote {options.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
