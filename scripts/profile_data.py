"""Measure what the downloaded readings actually look like, before anything is built on them.

    python scripts/profile_data.py

Writes reports/data-profile.md.

The point is to replace guesses with measurements. The proposal says a station is stale
after three hours, and that number was chosen because it sounded reasonable. If normal
stations routinely go four hours between readings, the gate fires constantly and gets turned
off; if outages are never shorter than twelve hours, the gate never fires at all and proves
nothing. Either way the threshold has to come from the gaps in the data, not from intuition.

The same applies to every contract test written later: a test that asserts a range nobody
measured is a test that fails on the first honest day.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
REPORT_PATH = PROJECT_ROOT / "reports" / "data-profile.md"

# Thailand's 24-hour ambient standard for PM2.5, in micrograms per cubic metre.
THAI_24H_STANDARD = 37.5


def parse_command_line() -> argparse.Namespace:
    """Command line for the profiler."""
    parser = argparse.ArgumentParser(description="Profile the downloaded readings")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def load_all_readings(raw_dir: Path) -> pd.DataFrame:
    """Read every station CSV into one frame, sorted by station then time."""
    paths = sorted(raw_dir.glob("station-*.csv"))
    if not paths:
        raise SystemExit(
            f"no station files in {raw_dir}. Run scripts/download_measurements.py, "
            f"or `dvc pull` to fetch the versioned copy."
        )

    frames = [pd.read_csv(path, parse_dates=["datetime_utc"]) for path in paths]
    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values(["location_id", "datetime_utc"]).reset_index(drop=True)


def measure_gaps(readings: pd.DataFrame) -> pd.Series:
    """Return the gap in hours between one reading and the next, per station.

    Computed within each station, never across them: the last reading of one station and
    the first of the next are not a gap, and treating them as one would invent outages
    that never happened.
    """
    gaps = readings.groupby("location_id")["datetime_utc"].diff()
    return gaps.dt.total_seconds().div(3600).dropna()


def describe_gaps(gaps: pd.Series) -> list[str]:
    """Turn the gap distribution into the lines that decide the staleness threshold."""
    lines = []
    total = len(gaps)

    normal = (gaps <= 1.0).mean()
    lines.append(f"- **{normal:.1%}** of consecutive readings are exactly one hour apart.")

    for threshold in (2, 3, 4, 6, 12, 24):
        proportion = (gaps > threshold).mean()
        count = int((gaps > threshold).sum())
        lines.append(
            f"- Gaps longer than **{threshold}h**: {proportion:.2%} of intervals "
            f"({count:,} of {total:,})"
        )

    lines.append(f"- Longest single gap: **{gaps.max():.0f} hours** "
                 f"({gaps.max() / 24:.1f} days)")
    return lines


def choose_staleness_threshold(gaps: pd.Series) -> tuple[int, str]:
    """Pick the smallest whole-hour threshold that fires rarely in normal operation.

    "Rarely" is defined as under one interval in two hundred. A gate that fires on more
    than that during healthy operation trains everyone to ignore it, and an ignored gate
    is worse than no gate, because it is also a claim that someone is watching.
    """
    target_false_alarm_rate = 0.005

    for threshold in range(2, 25):
        rate = (gaps > threshold).mean()
        if rate < target_false_alarm_rate:
            return threshold, (
                f"{threshold} hours, the smallest whole hour at which normal operation "
                f"trips the gate on only {rate:.2%} of intervals"
            )

    return 24, "24 hours; no shorter threshold is quiet enough in this data"


def find_impossible_values(readings: pd.DataFrame) -> list[str]:
    """Report readings that cannot be physically right, or are suspicious enough to name."""
    lines = []

    negatives = int((readings["pm25"] < 0).sum())
    lines.append(f"- Negative readings: **{negatives}**")

    exact_zeros = int((readings["pm25"] == 0).sum())
    lines.append(f"- Exactly zero: **{exact_zeros}** "
                 f"({exact_zeros / len(readings):.2%}) — a true zero is implausible outdoors "
                 f"and usually means a sensor fault")

    extreme = int((readings["pm25"] > 1000).sum())
    lines.append(f"- Above 1000 µg/m³: **{extreme}** — physically possible in a severe "
                 f"episode, but worth confirming before training on it")

    duplicated = int(readings.duplicated(["location_id", "datetime_utc"]).sum())
    lines.append(f"- Duplicate (station, hour) pairs: **{duplicated}**")

    return lines


def measure_persistence_baseline(readings: pd.DataFrame) -> list[str]:
    """Score the naive forecast that tomorrow's value is today's.

    Any model has to beat this to be worth deploying. Measuring it first stops the team
    celebrating a model that is quietly worse than doing nothing.
    """
    lines = []
    for horizon in (1, 3, 6):
        future = readings.groupby("location_id")["pm25"].shift(-horizon)
        comparable = readings["pm25"].notna() & future.notna()
        error = (future[comparable] - readings["pm25"][comparable]).abs()
        lines.append(
            f"- Persistence at **+{horizon}h**: mean absolute error "
            f"**{error.mean():.2f}** µg/m³, median **{error.median():.2f}**"
        )
    return lines


def main() -> int:
    """Profile the readings and write the report."""
    options = parse_command_line()
    readings = load_all_readings(options.raw_dir)
    gaps = measure_gaps(readings)
    threshold, threshold_reason = choose_staleness_threshold(gaps)

    station_hours = readings.groupby("location_id").size()
    span_hours = (readings["datetime_utc"].max()
                  - readings["datetime_utc"].min()).total_seconds() / 3600
    coverage = len(readings) / (span_hours * readings["location_id"].nunique())

    monthly = (readings.set_index("datetime_utc")["pm25"]
               .resample("ME").agg(["median", "max", "count"]))

    lines = [
        "# Data profile",
        "",
        "Measured from the downloaded readings by `scripts/profile_data.py`. Every number "
        "a later decision depends on is here, so that the decision can cite it.",
        "",
        "## Shape",
        "",
        f"- Stations: **{readings['location_id'].nunique()}**",
        f"- Readings: **{len(readings):,}**",
        f"- Window: **{readings['datetime_utc'].min():%Y-%m-%d}** to "
        f"**{readings['datetime_utc'].max():%Y-%m-%d}**",
        f"- Coverage: **{coverage:.1%}** of every possible station-hour",
        f"- Hours per station: min **{station_hours.min():,}**, "
        f"median **{int(station_hours.median()):,}**, max **{station_hours.max():,}**",
        "",
        "## Gaps between readings",
        "",
        "This section decides the staleness threshold, which the proposal had guessed at.",
        "",
        *describe_gaps(gaps),
        "",
        f"**Chosen threshold: {threshold} hours.** {threshold_reason.capitalize()}.",
        "",
        "A station whose newest reading is older than this is excluded from the forecast "
        "and reported as no data. The threshold is set from the gap distribution rather "
        "than chosen, because a gate that fires during healthy operation gets switched "
        "off, and a gate nobody trusts is worse than no gate at all — it also claims that "
        "someone is watching.",
        "",
        "## Values that cannot be right",
        "",
        *find_impossible_values(readings),
        "",
        "## The baseline any model must beat",
        "",
        "Persistence: predict that the value in N hours equals the value now.",
        "",
        *measure_persistence_baseline(readings),
        "",
        "Model accuracy carries no marks in this project, but a model that loses to "
        "persistence should not be deployed, and knowing the number in advance stops a "
        "worse model being mistaken for progress.",
        "",
        "## Monthly PM2.5",
        "",
        "| Month | Median | Max | Readings |",
        "|---|--:|--:|--:|",
    ]

    for timestamp, row in monthly.iterrows():
        lines.append(f"| {timestamp:%Y-%m} | {row['median']:.1f} | "
                     f"{row['max']:.0f} | {int(row['count']):,} |")

    above_standard = (readings["pm25"] > THAI_24H_STANDARD).mean()
    lines += [
        "",
        f"**{above_standard:.1%}** of all readings exceed Thailand's 24-hour standard of "
        f"{THAI_24H_STANDARD} µg/m³.",
        "",
        "The March and April figures are burning season. This is a real distribution "
        "shift, present in the data without anyone injecting it, and it is what the drift "
        "detection in this project has to catch.",
        "",
    ]

    options.out.parent.mkdir(parents=True, exist_ok=True)
    options.out.write_text("\n".join(lines))

    print("\n".join(lines[:4]))
    print(f"\nchosen staleness threshold: {threshold} hours")
    print(f"wrote {options.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
