"""The data contract, as functions rather than as tests.

The same rules have to run in two places. In CI they gate a commit; in the hourly job they
gate a batch before it reaches the model. Writing them once, here, is what stops those two
copies drifting apart — which they always do, and always in the direction of the serving
copy being weaker than the one anybody reviews.

Each check takes a frame and returns a list of violations. An empty list means the frame
satisfies that rule. Returning violations rather than raising lets the caller decide what
to do: CI fails the build, the hourly job drops the offending stations and carries on with
the rest, because refusing to forecast anywhere because one sensor is broken is its own kind
of outage.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

REQUIRED_COLUMNS = (
    "location_id", "sensor_id", "datetime_utc", "datetime_local",
    "pm25", "units", "latitude", "longitude",
)

EXPECTED_UNITS = "µg/m³"

# Thailand's land extent with slack at each edge.
THAILAND_BOUNDS = {"min_lat": 5.0, "max_lat": 21.0, "min_lon": 96.0, "max_lon": 106.5}

# Above this a reading is an instrument fault being reported as a measurement. The highest
# PM2.5 credibly recorded anywhere is in the low thousands.
PHYSICAL_CEILING = 2000.0

# A station needs this much history before lag features mean anything.
MINIMUM_HOURS_OF_HISTORY = 24 * 30


@dataclass(frozen=True)
class Violation:
    """One broken rule, with enough detail to act on without re-running anything."""

    rule: str
    detail: str
    row_count: int

    def __str__(self) -> str:
        """Render the violation the way it will appear in CI output."""
        return f"{self.rule}: {self.detail} ({self.row_count} rows)"


def check_required_columns(readings: pd.DataFrame) -> list[Violation]:
    """Every column the rest of the pipeline reads must be present."""
    missing = [column for column in REQUIRED_COLUMNS if column not in readings.columns]
    if not missing:
        return []
    return [Violation("required_columns", f"missing {missing}", len(readings))]


def check_no_duplicate_station_hours(readings: pd.DataFrame) -> list[Violation]:
    """One station reports one value per hour."""
    if not {"location_id", "datetime_utc"} <= set(readings.columns):
        return []

    duplicated = readings.duplicated(["location_id", "datetime_utc"])
    count = int(duplicated.sum())
    if count == 0:
        return []
    return [Violation(
        "duplicate_station_hours",
        "two readings for the same station and hour; a later groupby would average them",
        count,
    )]


def check_no_missing_concentrations(readings: pd.DataFrame) -> list[Violation]:
    """A null must never reach the file; downstream it usually becomes a zero."""
    if "pm25" not in readings.columns:
        return []

    count = int(readings["pm25"].isna().sum())
    if count == 0:
        return []
    return [Violation("missing_concentration", "pm25 is null", count)]


def check_concentrations_are_physically_possible(readings: pd.DataFrame) -> list[Violation]:
    """Concentrations below zero or above the ceiling are broken instruments."""
    if "pm25" not in readings.columns:
        return []

    violations = []

    negative_count = int((readings["pm25"] < 0).sum())
    if negative_count:
        violations.append(Violation(
            "negative_concentration",
            f"lowest {readings['pm25'].min()}",
            negative_count,
        ))

    above_ceiling = readings["pm25"] > PHYSICAL_CEILING
    ceiling_count = int(above_ceiling.sum())
    if ceiling_count:
        violations.append(Violation(
            "above_physical_ceiling",
            f"highest {readings.loc[above_ceiling, 'pm25'].max()} "
            f"exceeds {PHYSICAL_CEILING}",
            ceiling_count,
        ))

    return violations


def check_timestamps_are_hourly(readings: pd.DataFrame) -> list[Violation]:
    """Hourly data lands on the hour; anything else breaks lag features silently."""
    if "datetime_utc" not in readings.columns:
        return []

    timestamps = pd.to_datetime(readings["datetime_utc"], utc=True)
    unaligned = (timestamps.dt.minute != 0) | (timestamps.dt.second != 0)
    count = int(unaligned.sum())
    if count == 0:
        return []
    return [Violation(
        "unaligned_timestamp",
        "timestamps are not on the hour, so row shifts no longer mean a fixed interval",
        count,
    )]


def check_units_are_consistent(readings: pd.DataFrame) -> list[Violation]:
    """One station switching units rescales part of the training set invisibly."""
    if "units" not in readings.columns:
        return []

    units = set(readings["units"].dropna().unique())
    unexpected = units - {EXPECTED_UNITS}
    if not unexpected:
        return []
    return [Violation(
        "unexpected_units",
        f"expected only {EXPECTED_UNITS!r}, found {sorted(unexpected)}",
        int(readings["units"].isin(unexpected).sum()),
    )]


def check_coordinates_are_in_thailand(readings: pd.DataFrame) -> list[Violation]:
    """A station outside the country is mislabelled, and its weather is not our weather."""
    if not {"latitude", "longitude"} <= set(readings.columns):
        return []

    outside = (
        (readings["latitude"] < THAILAND_BOUNDS["min_lat"])
        | (readings["latitude"] > THAILAND_BOUNDS["max_lat"])
        | (readings["longitude"] < THAILAND_BOUNDS["min_lon"])
        | (readings["longitude"] > THAILAND_BOUNDS["max_lon"])
    )
    count = int(outside.sum())
    if count == 0:
        return []
    return [Violation(
        "coordinates_outside_thailand",
        f"stations {sorted(readings.loc[outside, 'location_id'].unique())}",
        count,
    )]


def check_stations_are_pinned(readings: pd.DataFrame,
                              pinned_location_ids: set[int]) -> list[Violation]:
    """Readings may only come from stations whose licence we recorded."""
    if "location_id" not in readings.columns:
        return []

    present = set(readings["location_id"].unique())
    unexpected = present - pinned_location_ids
    if not unexpected:
        return []
    return [Violation(
        "unpinned_station",
        f"stations {sorted(unexpected)} are not in the pinned list, so their licence "
        f"has not been checked",
        int(readings["location_id"].isin(unexpected).sum()),
    )]


def check_stations_have_enough_history(readings: pd.DataFrame) -> list[Violation]:
    """A station with too little history inflates counts without informing the model."""
    if "location_id" not in readings.columns:
        return []

    hours = readings.groupby("location_id").size()
    too_short = hours[hours < MINIMUM_HOURS_OF_HISTORY]
    if too_short.empty:
        return []
    return [Violation(
        "insufficient_history",
        f"under {MINIMUM_HOURS_OF_HISTORY} hours at stations {too_short.to_dict()}",
        int(too_short.sum()),
    )]


def validate(readings: pd.DataFrame,
             pinned_location_ids: set[int] | None = None) -> list[Violation]:
    """Run every contract rule and return everything that is wrong.

    All rules run even after one fails. Stopping at the first violation would mean fixing
    problems one build at a time, and a feed that broke in three ways takes three days to
    discover instead of one afternoon.
    """
    violations: list[Violation] = []
    violations += check_required_columns(readings)
    violations += check_no_duplicate_station_hours(readings)
    violations += check_no_missing_concentrations(readings)
    violations += check_concentrations_are_physically_possible(readings)
    violations += check_timestamps_are_hourly(readings)
    violations += check_units_are_consistent(readings)
    violations += check_coordinates_are_in_thailand(readings)
    violations += check_stations_have_enough_history(readings)

    if pinned_location_ids is not None:
        violations += check_stations_are_pinned(readings, pinned_location_ids)

    return violations
