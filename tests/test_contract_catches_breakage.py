"""Prove every contract rule fires when the thing it guards against actually happens.

A contract that has only ever been run against good data is untested. It passes, and nobody
knows whether it passes because the data is sound or because the rule is inert — a typo in a
comparison, a column name that no longer exists, a filter that silently matches nothing.
Both look identical from the outside: a green suite.

So each test here takes a clean frame, breaks it in exactly one way, and asserts the
matching rule reports it. If someone later weakens a rule, the corresponding test here goes
red, which is the only way a gate stays a gate.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import contract


def make_clean_readings(hours: int = 24 * 40, station_count: int = 2) -> pd.DataFrame:
    """Build a small frame that satisfies every rule, as the starting point for breaking it.

    Deliberately synthetic rather than a slice of the real data: a fixture built from real
    readings would start failing whenever the download changed, and these tests are about
    the rules, not about the feed.
    """
    rows = []
    for index in range(station_count):
        location_id = 1000 + index
        timestamps = pd.date_range("2026-01-01", periods=hours, freq="h", tz="UTC")
        for offset, timestamp in enumerate(timestamps):
            rows.append({
                "location_id": location_id,
                "sensor_id": 5000 + index,
                "datetime_utc": timestamp,
                "datetime_local": timestamp.tz_convert("Asia/Bangkok"),
                "pm25": 10.0 + (offset % 20),
                "units": contract.EXPECTED_UNITS,
                "latitude": 13.75,
                "longitude": 100.5,
            })
    return pd.DataFrame(rows)


@pytest.fixture()
def clean() -> pd.DataFrame:
    """A frame that must pass everything."""
    return make_clean_readings()


def rules_broken(violations: list[contract.Violation]) -> set[str]:
    """Return the set of rule names reported, for readable assertions."""
    return {violation.rule for violation in violations}


def test_clean_data_reports_no_violations(clean: pd.DataFrame) -> None:
    """The starting point must be genuinely clean, or every test below proves nothing."""
    violations = contract.validate(clean, pinned_location_ids={1000, 1001})
    assert violations == [], f"clean fixture is not clean: {[str(v) for v in violations]}"


def test_a_dropped_column_is_caught(clean: pd.DataFrame) -> None:
    """The upstream feed renames or removes a field."""
    broken = clean.drop(columns=["units"])
    assert "required_columns" in rules_broken(contract.validate(broken))


def test_a_duplicated_hour_is_caught(clean: pd.DataFrame) -> None:
    """The same batch is ingested twice, or a merge fans out."""
    broken = pd.concat([clean, clean.iloc[[0]]], ignore_index=True)
    assert "duplicate_station_hours" in rules_broken(contract.validate(broken))


def test_a_null_concentration_is_caught(clean: pd.DataFrame) -> None:
    """A missing reading reaches the file instead of being skipped."""
    broken = clean.copy()
    broken.loc[5, "pm25"] = None
    assert "missing_concentration" in rules_broken(contract.validate(broken))


def test_a_negative_concentration_is_caught(clean: pd.DataFrame) -> None:
    """A sensor reports below zero, which is not a low reading but a broken one."""
    broken = clean.copy()
    broken.loc[7, "pm25"] = -3.2
    assert "negative_concentration" in rules_broken(contract.validate(broken))


def test_a_reading_above_the_ceiling_is_caught(clean: pd.DataFrame) -> None:
    """An instrument fault arrives as a very large number."""
    broken = clean.copy()
    broken.loc[9, "pm25"] = contract.PHYSICAL_CEILING + 1
    assert "above_physical_ceiling" in rules_broken(contract.validate(broken))


def test_an_unaligned_timestamp_is_caught(clean: pd.DataFrame) -> None:
    """The endpoint changes aggregation and stops landing on the hour.

    This is the quietest failure in the contract. The values stay plausible, so nothing
    downstream complains; only the meaning of a lag feature changes.
    """
    broken = clean.copy()
    broken.loc[11, "datetime_utc"] = broken.loc[11, "datetime_utc"] + pd.Timedelta(minutes=17)
    assert "unaligned_timestamp" in rules_broken(contract.validate(broken))


def test_a_unit_change_is_caught(clean: pd.DataFrame) -> None:
    """One station starts reporting in different units."""
    broken = clean.copy()
    broken.loc[13, "units"] = "mg/m³"
    assert "unexpected_units" in rules_broken(contract.validate(broken))


def test_a_station_outside_thailand_is_caught(clean: pd.DataFrame) -> None:
    """A mislabelled station, or a country filter that stopped filtering."""
    broken = clean.copy()
    broken.loc[15, "latitude"] = 51.5
    broken.loc[15, "longitude"] = -0.12
    assert "coordinates_outside_thailand" in rules_broken(contract.validate(broken))


def test_an_unpinned_station_is_caught(clean: pd.DataFrame) -> None:
    """Readings appear from a station whose licence was never checked."""
    broken = clean.copy()
    broken.loc[17, "location_id"] = 999999
    violations = contract.validate(broken, pinned_location_ids={1000, 1001})
    assert "unpinned_station" in rules_broken(violations)


def test_a_station_with_too_little_history_is_caught() -> None:
    """A station is present in the file but has no usable window."""
    broken = make_clean_readings(hours=24 * 5, station_count=1)
    assert "insufficient_history" in rules_broken(contract.validate(broken))


def test_several_breakages_are_all_reported_at_once(clean: pd.DataFrame) -> None:
    """Validation must not stop at the first problem.

    A feed that broke in three ways should take one afternoon to diagnose, not three
    builds. This is the rule that makes the difference, and it is easy to lose in a
    refactor that swaps the loop for an early return.
    """
    broken = clean.copy()
    broken.loc[3, "pm25"] = -1.0
    broken.loc[4, "units"] = "ppm"
    broken.loc[5, "latitude"] = 0.0

    reported = rules_broken(contract.validate(broken))
    assert {"negative_concentration", "unexpected_units",
            "coordinates_outside_thailand"} <= reported
