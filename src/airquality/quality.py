"""Per-station quality screening: which sensors are fit to train on.

This is deliberately separate from src/contract.py, and the difference decides what happens
when a rule fires.

A *contract* failure means the feed broke — a renamed column, a unit change, a timestamp
that stopped landing on the hour. Nothing downstream is trustworthy, so the pipeline stops.

A *quality* failure means one sensor is broken, which is the normal condition of any real
sensor network. Stopping everything because one device is faulty would mean nobody can ship
until a third party repairs hardware we do not own. So the station is excluded, the reason is
recorded, and the rest of the fleet carries on.

Every threshold here is set from the measured distribution rather than chosen, and each one
sits inside a wide gap between the bad stations and the rest, so the result does not depend
on the exact value picked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# A station reporting an exact zero more often than this is not measuring clean air.
# Measured: the three worst stations sit at 17.79%, 8.05% and 7.75%; the fourth is at
# 1.48%. Any threshold between 1.5% and 7.7% selects the same three, so the answer is not
# sensitive to this number.
MAXIMUM_ZERO_RATE = 0.05

# A reading that barely moves for this many consecutive hours is a stuck instrument.
# Measured: half of all stations never exceed 5 hours and 95% stay under 15. The one
# faulty station ran 52 hours; the next highest is 21.
MAXIMUM_FLAT_RUN_HOURS = 24

# Two consecutive readings are "the same" if they differ by less than this fraction.
FLAT_RUN_TOLERANCE = 0.01


@dataclass
class Exclusion:
    """One station kept out of training, with the evidence that put it there."""

    location_id: int
    reason: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Render the exclusion for a log or a report."""
        return f"station {self.location_id}: {self.reason} — {self.detail}"


def longest_flat_run(values: pd.Series,
                     tolerance: float = FLAT_RUN_TOLERANCE) -> int:
    """Return the longest run of consecutive readings that barely change.

    A working outdoor sensor never holds still: PM2.5 moves with traffic, wind and time of
    day. A long flat run is the signature of an instrument that has stopped measuring and
    started repeating, which is a different fault from going silent — and a more dangerous
    one, because the readings keep arriving with fresh timestamps.
    """
    if values.empty:
        return 0

    moved = (values.diff().abs() > values.abs() * tolerance).fillna(True)
    run_identifier = moved.cumsum()
    return int(run_identifier.value_counts().max())


def screen_station(location_id: int, readings: pd.DataFrame) -> list[Exclusion]:
    """Return every reason this one station should be kept out of training."""
    exclusions = []

    if readings.empty:
        return [Exclusion(
            location_id,
            "no_readings",
            "pinned but returned no data at all",
            {"row_count": 0},
        )]

    values = readings["pm25"]

    zero_rate = float((values == 0).mean())
    if zero_rate > MAXIMUM_ZERO_RATE:
        exclusions.append(Exclusion(
            location_id,
            "implausible_zero_rate",
            f"reports an exact zero in {zero_rate:.1%} of readings, above the "
            f"{MAXIMUM_ZERO_RATE:.0%} limit; a true zero outdoors is not a measurement",
            {"zero_rate": round(zero_rate, 4), "row_count": len(values)},
        ))

    flat_run = longest_flat_run(values)
    if flat_run >= MAXIMUM_FLAT_RUN_HOURS:
        exclusions.append(Exclusion(
            location_id,
            "stuck_sensor",
            f"held the same value for {flat_run} consecutive hours; the air does not "
            f"stand still for a day",
            {"longest_flat_run_hours": flat_run,
             "value_during_run": float(values.median())},
        ))

    return exclusions


def screen_all(readings: pd.DataFrame,
               pinned_location_ids: set[int]) -> list[Exclusion]:
    """Screen every pinned station, including ones that returned nothing.

    Pinned stations with no rows are screened too. A station that silently disappears from
    the dataset is worse than one that is excluded with a reason, because every later count
    of "how many stations do we have" quietly disagrees with the pinned list.
    """
    exclusions: list[Exclusion] = []

    for location_id in sorted(pinned_location_ids):
        station_readings = readings[readings["location_id"] == location_id]
        exclusions.extend(screen_station(location_id, station_readings))

    return exclusions


def excluded_location_ids(exclusions: list[Exclusion]) -> set[int]:
    """Return just the station ids, for filtering a training frame."""
    return {exclusion.location_id for exclusion in exclusions}
