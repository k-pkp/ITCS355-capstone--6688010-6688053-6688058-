"""Prove the quality screen catches each kind of broken sensor, and spares working ones.

The second half matters as much as the first. A screen that excludes everything is as
useless as one that excludes nothing, and it is easier to write by accident: tighten a
threshold slightly, and a rule that was catching three faulty sensors starts catching
half the fleet without anyone noticing, because the pipeline still runs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.airquality import quality


def make_station_readings(location_id: int, values: list[float]) -> pd.DataFrame:
    """Build one station's readings from a list of concentrations."""
    timestamps = pd.date_range("2026-01-01", periods=len(values), freq="h", tz="UTC")
    return pd.DataFrame({
        "location_id": location_id,
        "datetime_utc": timestamps,
        "pm25": values,
    })


def realistic_values(count: int, seed: int = 20260101) -> list[float]:
    """Concentrations that move the way a working outdoor sensor's do.

    Built from a fixed seed so the test is repeatable: a screen test that passes or fails
    depending on the day's random numbers is not a test.
    """
    generator = np.random.default_rng(seed)
    hours = np.arange(count)
    daily_cycle = 8 + 4 * np.sin(2 * np.pi * hours / 24)
    noise = generator.normal(0, 1.5, count)
    return list(np.clip(daily_cycle + noise, 0.5, None))


@pytest.fixture()
def healthy() -> pd.DataFrame:
    """A station that should never be excluded."""
    return make_station_readings(1000, realistic_values(24 * 60))


def reasons_for(exclusions: list[quality.Exclusion]) -> set[str]:
    """The set of reasons reported, for readable assertions."""
    return {exclusion.reason for exclusion in exclusions}


def test_a_healthy_station_is_not_excluded(healthy: pd.DataFrame) -> None:
    """The screen must leave working sensors alone."""
    exclusions = quality.screen_station(1000, healthy)
    assert exclusions == [], [str(exclusion) for exclusion in exclusions]


def test_a_station_with_no_readings_is_excluded() -> None:
    """A pinned station that returned nothing is recorded, not silently dropped."""
    empty = pd.DataFrame(columns=["location_id", "datetime_utc", "pm25"])
    exclusions = quality.screen_station(2142801, empty)
    assert reasons_for(exclusions) == {"no_readings"}


def test_a_station_reporting_many_exact_zeros_is_excluded(healthy: pd.DataFrame) -> None:
    """An exact zero outdoors is a fault reported as a measurement."""
    broken = healthy.copy()
    zero_count = int(len(broken) * 0.10)
    broken.loc[broken.index[:zero_count], "pm25"] = 0.0

    exclusions = quality.screen_station(1000, broken)
    assert "implausible_zero_rate" in reasons_for(exclusions)


def test_a_few_zeros_do_not_exclude_a_station(healthy: pd.DataFrame) -> None:
    """Below the threshold, a zero is noise rather than evidence.

    25 of 39 real stations report at least one exact zero. If any zero excluded a station,
    the screen would throw away most of a working fleet.
    """
    slightly_broken = healthy.copy()
    zero_count = int(len(slightly_broken) * 0.01)
    slightly_broken.loc[slightly_broken.index[:zero_count], "pm25"] = 0.0

    exclusions = quality.screen_station(1000, slightly_broken)
    assert "implausible_zero_rate" not in reasons_for(exclusions)


def test_a_stuck_sensor_is_excluded() -> None:
    """A sensor repeating one value still reports fresh timestamps.

    This is the fault the staleness gate cannot see: the data is current, and wrong.
    """
    values = realistic_values(24 * 60)
    values[100:100 + 48] = [1680.0] * 48
    stuck = make_station_readings(2457250, values)

    exclusions = quality.screen_station(2457250, stuck)
    assert "stuck_sensor" in reasons_for(exclusions)


def test_a_stuck_sensor_is_caught_even_at_a_plausible_value() -> None:
    """Being stuck is the fault, not being stuck at a large number.

    A sensor frozen at 12 µg/m³ passes every range check ever written, and reports clean
    air through an episode that never reaches it.
    """
    values = realistic_values(24 * 60)
    values[200:200 + 36] = [12.0] * 36
    stuck = make_station_readings(3000, values)

    exclusions = quality.screen_station(3000, stuck)
    assert "stuck_sensor" in reasons_for(exclusions)


def test_a_short_flat_stretch_does_not_exclude_a_station(healthy: pd.DataFrame) -> None:
    """Still air for a few hours is weather, not a fault."""
    briefly_flat = healthy.copy()
    briefly_flat.loc[briefly_flat.index[50:56], "pm25"] = 9.0

    exclusions = quality.screen_station(1000, briefly_flat)
    assert "stuck_sensor" not in reasons_for(exclusions)


def test_one_station_can_fail_for_several_reasons() -> None:
    """Both faults are reported, so a fix for one does not hide the other."""
    values = realistic_values(24 * 60)
    values[:200] = [0.0] * 200
    values[300:300 + 40] = [500.0] * 40
    doubly_broken = make_station_readings(4000, values)

    exclusions = quality.screen_station(4000, doubly_broken)
    assert {"implausible_zero_rate", "stuck_sensor"} <= reasons_for(exclusions)


def test_screening_covers_pinned_stations_that_are_absent(healthy: pd.DataFrame) -> None:
    """A pinned station missing from the readings must still be accounted for."""
    exclusions = quality.screen_all(healthy, pinned_location_ids={1000, 9999})

    absent = [exclusion for exclusion in exclusions if exclusion.location_id == 9999]
    assert absent, "a pinned station with no rows vanished instead of being excluded"
    assert absent[0].reason == "no_readings"
