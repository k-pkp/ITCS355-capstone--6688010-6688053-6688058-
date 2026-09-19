"""Run the data contract against the actual downloaded readings.

The rules live in src/contract.py so that CI and the hourly serving job apply the same ones.
This file is deliberately thin: it loads the real data and asserts the contract is
satisfied. Anything more here would be a second copy of the rules, and second copies drift.

What each rule protects against, and proof that each one fires when it should, is in
tests/test_contract_catches_breakage.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.airquality import contract

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
STATIONS_FILE = PROJECT_ROOT / "data" / "stations.json"


@pytest.fixture(scope="module")
def readings() -> pd.DataFrame:
    """Every downloaded reading, as one frame."""
    paths = sorted(RAW_DIR.glob("station-*.csv"))
    if not paths:
        pytest.skip(f"no data in {RAW_DIR}; run `dvc pull` or the download script")

    frames = [pd.read_csv(path, parse_dates=["datetime_utc"]) for path in paths]
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="module")
def pinned_station_ids() -> set[int]:
    """The station ids we pinned and recorded a licence for."""
    if not STATIONS_FILE.exists():
        pytest.skip(f"{STATIONS_FILE} missing; run scripts/find_stations.py")
    payload = json.loads(STATIONS_FILE.read_text())
    return {station["location_id"] for station in payload["stations"]}


def test_downloaded_readings_satisfy_the_contract(readings: pd.DataFrame,
                                                  pinned_station_ids: set[int]) -> None:
    """The whole contract, against the whole dataset."""
    violations = contract.validate(readings, pinned_location_ids=pinned_station_ids)
    assert violations == [], "\n".join(str(violation) for violation in violations)


def test_every_pinned_station_states_a_licence() -> None:
    """The dataset's licence answer must be complete, not mostly complete.

    This is about the station list rather than the readings, so it is not part of the
    frame contract. It matters just as much: one station without a licence makes the
    whole dataset's licence unanswerable.
    """
    payload = json.loads(STATIONS_FILE.read_text())
    unlicensed = [station["location_id"] for station in payload["stations"]
                  if not station.get("licence")]
    assert not unlicensed, f"{len(unlicensed)} pinned stations state no licence: {unlicensed}"
