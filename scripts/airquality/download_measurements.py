"""Download the hourly PM2.5 history for the pinned stations.

    python scripts/download_measurements.py --months 6

Reads data/stations.json, fetches each station's hourly readings, and writes one CSV per
station under data/raw/. The model is trained from these files and never from the live API,
so training can be repeated on a laptop with no network and no key.

Downloading is resumable. Each station's file is written once and skipped on a later run,
because a six-month pull across forty stations is long enough that something will interrupt
it — a dropped connection, a rate limit, a closed laptop — and starting again from zero
every time is how a download that should take an hour never finishes at all.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openaq_client import OpenAQClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIONS_FILE = PROJECT_ROOT / "data" / "stations.json"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

CSV_COLUMNS = [
    "location_id", "sensor_id", "datetime_utc", "datetime_local",
    "pm25", "units", "latitude", "longitude",
]


def parse_command_line() -> argparse.Namespace:
    """Command line for the history download."""
    parser = argparse.ArgumentParser(description="Download hourly PM2.5 history")
    parser.add_argument("--months", type=int, default=6,
                        help="how far back to fetch")
    parser.add_argument("--stations", type=Path, default=STATIONS_FILE)
    parser.add_argument("--out-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--only", type=int, default=None,
                        help="fetch only this many stations, for a quick check first")
    parser.add_argument("--force", action="store_true",
                        help="re-download stations that already have a file")
    return parser.parse_args()


def load_stations(path: Path) -> list[dict]:
    """Read the pinned station list, with a clear error if it is not there yet."""
    if not path.exists():
        raise SystemExit(
            f"{path} not found. Run scripts/find_stations.py first — it pins which "
            f"stations this project uses and records their licences."
        )
    return json.loads(path.read_text())["stations"]


def rows_from_response(station: dict, results: list[dict]) -> list[dict]:
    """Turn one page of OpenAQ hourly results into rows for the CSV."""
    rows = []
    for measurement in results:
        period = measurement.get("period") or {}
        timestamp = period.get("datetimeFrom") or {}

        value = measurement.get("value")
        if value is None:
            # A missing hour is genuinely missing. Writing a zero here would turn "we
            # have no reading" into "the air was perfectly clean", which is the exact
            # confusion this project's failure demo is about.
            continue

        rows.append({
            "location_id": station["location_id"],
            "sensor_id": station["sensor_id"],
            "datetime_utc": timestamp.get("utc"),
            "datetime_local": timestamp.get("local"),
            "pm25": value,
            "units": station.get("units"),
            "latitude": station.get("latitude"),
            "longitude": station.get("longitude"),
        })
    return rows


def download_station(client: OpenAQClient, station: dict,
                     date_from: datetime, date_to: datetime) -> list[dict]:
    """Fetch one station's hourly readings over the requested window."""
    results = client.get_all_pages(
        f"sensors/{station['sensor_id']}/hours",
        {
            "datetime_from": date_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datetime_to": date_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 1000,
        },
        page_limit=400,
    )
    return rows_from_response(station, results)


def write_csv(path: Path, rows: list[dict]) -> None:
    """Write one station's rows, oldest first."""
    rows.sort(key=lambda row: row["datetime_utc"] or "")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    """Download every pinned station that does not already have a file."""
    options = parse_command_line()
    stations = load_stations(options.stations)
    if options.only:
        stations = stations[:options.only]

    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=30 * options.months)

    print(f"{len(stations)} stations · {date_from:%Y-%m-%d} to {date_to:%Y-%m-%d}\n",
          flush=True)

    client = OpenAQClient()
    total_rows = 0
    skipped = 0
    empty_stations = []

    for index, station in enumerate(stations, start=1):
        target = options.out_dir / f"station-{station['location_id']}.csv"
        label = f"[{index}/{len(stations)}] {station['location_id']} {station.get('name') or ''}"

        if target.exists() and not options.force:
            print(f"{label}: already downloaded, skipping")
            skipped += 1
            continue

        rows = download_station(client, station, date_from, date_to)
        if not rows:
            print(f"{label}: no readings in this window")
            empty_stations.append(station["location_id"])
            continue

        write_csv(target, rows)
        total_rows += len(rows)
        print(f"{label}: {len(rows)} hours -> {target.name}", flush=True)

    print(f"\n{total_rows} rows written, {skipped} stations skipped as already present")

    if empty_stations:
        print(f"{len(empty_stations)} stations returned nothing: {empty_stations}")
        print("Those are pinned but silent. Decide whether to drop them from "
              "data/stations.json before training, and say which you dropped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
