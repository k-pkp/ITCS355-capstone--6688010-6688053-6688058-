"""Find the Thai PM2.5 stations this project will use, and record their licences.

    python scripts/find_stations.py --country TH --limit 40

Writes data/stations.json, which is the list every later step reads. Pinning the stations
once, in a file, is what makes the dataset reproducible: "all Thai stations" is a different
set of stations every month, and a model trained on one of those sets cannot be rebuilt
from the other.

The licence is captured here rather than looked up later. OpenAQ aggregates from many
providers whose terms differ, so there is no single licence for "OpenAQ data" — the answer
depends on which stations you chose, which is exactly the decision this script records.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from openaq_client import OpenAQClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIONS_FILE = PROJECT_ROOT / "data" / "stations.json"

# OpenAQ's id for PM2.5 in micrograms per cubic metre.
PM25_PARAMETER_ID = 2


def parse_command_line() -> argparse.Namespace:
    """Command line for the station search."""
    parser = argparse.ArgumentParser(description="Pin the stations this project uses")
    parser.add_argument("--country", default="TH",
                        help="ISO country code, default TH for Thailand")
    parser.add_argument("--limit", type=int, default=40,
                        help="how many stations to keep, after sorting by recency")
    parser.add_argument("--out", type=Path, default=STATIONS_FILE)
    parser.add_argument("--allow-unstated-licence", action="store_true",
                        help="keep stations whose licence OpenAQ does not state. Off by "
                             "default: an unstated licence is not a permissive one, and "
                             "the proposal has to name the licence it relies on.")
    return parser.parse_args()


def describe_sensor(location: dict) -> dict | None:
    """Return the PM2.5 sensor on this location, or None if it has none."""
    for sensor in location.get("sensors", []):
        parameter = sensor.get("parameter", {})
        if parameter.get("id") == PM25_PARAMETER_ID:
            return {
                "sensor_id": sensor["id"],
                "parameter": parameter.get("name"),
                "units": parameter.get("units"),
            }
    return None


def last_reported_at(location: dict) -> str:
    """Return the location's newest reading time, or an empty string if it has none."""
    datetime_last = location.get("datetimeLast") or {}
    return datetime_last.get("utc") or ""


def main() -> int:
    """Search for stations, keep the ones that are actually reporting, and save them."""
    options = parse_command_line()
    client = OpenAQClient()

    print(f"searching OpenAQ for PM2.5 stations in {options.country}", flush=True)
    locations = client.get_all_pages("locations", {
        "iso": options.country,
        "parameters_id": PM25_PARAMETER_ID,
        "limit": 100,
    })
    print(f"  {len(locations)} locations returned", flush=True)

    usable = []
    unstated: list[int] = []
    for location in locations:
        sensor = describe_sensor(location)
        if sensor is None:
            continue

        reported_at = last_reported_at(location)
        if not reported_at:
            continue

        licences = location.get("licenses") or []
        licence_name = licences[0].get("name") if licences else None
        if licence_name is None and not options.allow_unstated_licence:
            unstated.append(location["id"])
            continue

        coordinates = location.get("coordinates") or {}
        usable.append({
            "location_id": location["id"],
            "name": location.get("name"),
            "locality": location.get("locality"),
            "latitude": coordinates.get("latitude"),
            "longitude": coordinates.get("longitude"),
            "timezone": location.get("timezone"),
            "provider": (location.get("provider") or {}).get("name"),
            "owner": (location.get("owner") or {}).get("name"),
            "licence": licence_name,
            "last_reported_utc": reported_at,
            **sensor,
        })

    # Newest first: a station that stopped reporting two years ago is not a station.
    usable.sort(key=lambda station: station["last_reported_utc"], reverse=True)
    chosen = usable[:options.limit]

    licence_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    for station in chosen:
        licence = station["licence"] or "UNSTATED"
        provider = station["provider"] or "unknown"
        licence_counts[licence] = licence_counts.get(licence, 0) + 1
        provider_counts[provider] = provider_counts.get(provider, 0) + 1

    payload = {
        "pinned_at_utc": datetime.now(timezone.utc).isoformat(),
        "country": options.country,
        "parameter": "pm25",
        "station_count": len(chosen),
        "licences": licence_counts,
        "providers": provider_counts,
        "stations": chosen,
    }

    options.out.parent.mkdir(parents=True, exist_ok=True)
    options.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print(f"\nkept {len(chosen)} of {len(usable)} reporting stations")
    print(f"wrote {options.out}\n")

    print("providers:")
    for provider, count in sorted(provider_counts.items(), key=lambda item: -item[1]):
        print(f"  {count:>3}  {provider}")

    print("\nlicences (this is what the proposal must name):")
    for licence, count in sorted(licence_counts.items(), key=lambda item: -item[1]):
        print(f"  {count:>3}  {licence}")

    if unstated:
        print(f"\nskipped {len(unstated)} stations whose licence OpenAQ does not state. "
              f"Pass --allow-unstated-licence to keep them, but the proposal then has to "
              f"explain what you are relying on instead of a licence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
